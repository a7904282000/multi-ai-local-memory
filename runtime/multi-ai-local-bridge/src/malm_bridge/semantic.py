from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import unicodedata
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .storage.base import StorageAdapter
from .types import MemoryAtom


_INDEX_VERSION = 1
_MAX_REBUILD_ITEMS = 1_000_000
_WORD_RE = re.compile(r"[a-z0-9_]+", re.I)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")

# Orthographic normalization only. This does not rewrite source memory; it exists solely
# in the disposable derived index.
_EQUIVALENTS = {
    "colour": "color",
    "colours": "color",
    "favorite": "favorite",
    "favourite": "favorite",
    "favorites": "favorite",
    "favourites": "favorite",
    "preferences": "preference",
    "prefs": "preference",
}


def _source_sha256(atom: MemoryAtom) -> str:
    """Fingerprint the canonical source atom without mutating or normalizing it."""
    raw = json.dumps(atom.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _english_tokens(text: str) -> list[str]:
    out: list[str] = []
    for raw in _WORD_RE.findall(_normalize_text(text)):
        token = _EQUIVALENTS.get(raw, raw)
        if len(token) > 4 and token.endswith("ies"):
            token = token[:-3] + "y"
        elif len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        out.append(token)
    return out


def _cjk_ngrams(text: str) -> list[str]:
    chars = "".join(_CJK_RE.findall(_normalize_text(text)))
    if not chars:
        return []
    grams: list[str] = list(chars)
    grams.extend(chars[i:i + 2] for i in range(max(0, len(chars) - 1)))
    grams.extend(chars[i:i + 3] for i in range(max(0, len(chars) - 2)))
    return grams


def _ascii_char_ngrams(text: str) -> list[str]:
    compact = re.sub(r"[^a-z0-9]+", "", _normalize_text(text))
    if len(compact) < 3:
        return [compact] if compact else []
    return [compact[i:i + 3] for i in range(len(compact) - 2)]


def _h(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _features_for_text(text: str, *, prefix: str = "body", weight: float = 1.0) -> dict[str, float]:
    counts: Counter[str] = Counter()
    for token in _english_tokens(text):
        counts[f"w:{_h(token)}"] += 3
    for gram in _cjk_ngrams(text):
        counts[f"c:{_h(gram)}"] += 2 if len(gram) > 1 else 1
    for gram in _ascii_char_ngrams(text):
        counts[f"a:{_h(gram)}"] += 1
    return {f"{prefix}:{k}": float(v) * weight for k, v in counts.items()}


def _merge_features(*parts: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in parts:
        for k, v in part.items():
            out[k] = out.get(k, 0.0) + v
    return out


def _atom_features(atom: MemoryAtom) -> dict[str, float]:
    # Field weights are derived ranking hints only; source fields remain untouched.
    metadata = " ".join([atom.kind, atom.key, *atom.tags])
    return _merge_features(
        _features_for_text(atom.content, prefix="x", weight=1.0),
        _features_for_text(metadata, prefix="x", weight=1.35),
    )


def _query_features(query: str) -> dict[str, float]:
    return _features_for_text(query, prefix="x", weight=1.0)


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    if dot <= 0:
        return 0.0
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


class DerivedSemanticIndex:
    """Disposable, rebuildable recall index over an authoritative StorageAdapter.

    Invariants:
    - The index never writes to source memory.
    - It stores only hashed/derived features plus source identity/revision/hash.
    - Search returns fresh MemoryAtom objects fetched from the authoritative storage.
    - Deleting or corrupting this database never loses memory; it is rebuilt from source.
    """

    def __init__(self, db_path: str | Path, storage: StorageAdapter):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage = storage
        self._lock = threading.RLock()
        self._init_or_recover()

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        try:
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=FULL")
            return c
        except Exception:
            c.close()
            raise

    @contextmanager
    def _db(self):
        c = self._connect()
        try:
            yield c
        finally:
            c.close()

    def _init_schema(self) -> None:
        with self._db() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS derived_docs (
                    memory_id TEXT PRIMARY KEY,
                    memory_space_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    lifecycle_status TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    source_updated_at TEXT NOT NULL,
                    features_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_derived_space_ns_lifecycle
                    ON derived_docs(memory_space_id, namespace, lifecycle_status);
                """
            )
            c.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('index_version',?)",
                (str(_INDEX_VERSION),),
            )

    def _init_or_recover(self) -> None:
        try:
            self._init_schema()
            with self._db() as c:
                c.execute("PRAGMA quick_check").fetchone()
        except sqlite3.DatabaseError:
            self._discard_corrupt_index()
            self._init_schema()

    def _discard_corrupt_index(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self.db_path) + suffix)
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass

    def reset(self) -> None:
        """Delete only derived data. Authoritative memory is untouched."""
        with self._lock:
            self._discard_corrupt_index()
            self._init_schema()

    def _source_atoms(self, memory_space_id: str, namespaces: list[str], include_lifecycle: list[str]) -> list[MemoryAtom]:
        return self.storage.search(
            "",
            {
                "memory_space_ids": [memory_space_id],
                "namespaces": namespaces,
                "include_lifecycle": include_lifecycle,
            },
            _MAX_REBUILD_ITEMS,
        )

    def rebuild_space(
        self,
        memory_space_id: str,
        *,
        namespaces: list[str] | None = None,
        include_lifecycle: list[str] | None = None,
    ) -> dict[str, int]:
        namespaces = list(namespaces or [])
        include_lifecycle = list(include_lifecycle or ["ACTIVE", "CONFLICT"])
        atoms = self._source_atoms(memory_space_id, namespaces, include_lifecycle)
        rows = []
        for atom in atoms:
            rows.append((
                atom.memory_id,
                atom.memory_space_id,
                atom.namespace,
                atom.lifecycle_status,
                atom.revision,
                _source_sha256(atom),
                atom.updated_at,
                json.dumps(_atom_features(atom), sort_keys=True, separators=(",", ":")),
            ))
        ids = {r[0] for r in rows}
        with self._lock:
            try:
                with self._db() as c:
                    c.execute("BEGIN IMMEDIATE")
                    existing = {
                        r[0] for r in c.execute(
                            "SELECT memory_id FROM derived_docs WHERE memory_space_id=?",
                            (memory_space_id,),
                        )
                    }
                    for row in rows:
                        c.execute(
                            """
                            INSERT INTO derived_docs(memory_id,memory_space_id,namespace,lifecycle_status,revision,source_sha256,source_updated_at,features_json)
                            VALUES(?,?,?,?,?,?,?,?)
                            ON CONFLICT(memory_id) DO UPDATE SET
                              memory_space_id=excluded.memory_space_id,
                              namespace=excluded.namespace,
                              lifecycle_status=excluded.lifecycle_status,
                              revision=excluded.revision,
                              source_sha256=excluded.source_sha256,
                              source_updated_at=excluded.source_updated_at,
                              features_json=excluded.features_json
                            """,
                            row,
                        )
                    stale = existing - ids
                    if stale:
                        c.executemany("DELETE FROM derived_docs WHERE memory_id=?", [(x,) for x in stale])
                    c.execute("COMMIT")
            except sqlite3.DatabaseError:
                self._discard_corrupt_index()
                self._init_schema()
                return self.rebuild_space(memory_space_id, namespaces=namespaces, include_lifecycle=include_lifecycle)
        return {"indexed": len(rows), "removed": len(existing - ids)}

    def search(
        self,
        query: str,
        *,
        memory_space_id: str,
        namespaces: list[str] | None = None,
        include_lifecycle: list[str] | None = None,
        limit: int = 12,
    ) -> list[MemoryAtom]:
        namespaces = list(namespaces or [])
        include_lifecycle = list(include_lifecycle or ["ACTIVE", "CONFLICT"])
        self.rebuild_space(memory_space_id, namespaces=namespaces, include_lifecycle=include_lifecycle)
        if limit <= 0:
            return []
        qf = _query_features(query)
        clauses = ["memory_space_id=?"]
        params: list[Any] = [memory_space_id]
        if namespaces:
            clauses.append("namespace IN (%s)" % ",".join("?" for _ in namespaces))
            params.extend(namespaces)
        if include_lifecycle:
            clauses.append("lifecycle_status IN (%s)" % ",".join("?" for _ in include_lifecycle))
            params.extend(include_lifecycle)
        with self._lock:
            try:
                with self._db() as c:
                    rows = list(c.execute(
                        "SELECT * FROM derived_docs WHERE " + " AND ".join(clauses),
                        params,
                    ))
            except sqlite3.DatabaseError:
                self._discard_corrupt_index()
                self._init_schema()
                return self.search(
                    query,
                    memory_space_id=memory_space_id,
                    namespaces=namespaces,
                    include_lifecycle=include_lifecycle,
                    limit=limit,
                )

        scored: list[tuple[float, str, int, str]] = []
        for row in rows:
            features = json.loads(row["features_json"])
            score = 1.0 if not query.strip() else _cosine(qf, features)
            if query.strip() and score <= 0:
                continue
            scored.append((score, row["memory_id"], int(row["revision"]), row["source_sha256"]))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

        result: list[MemoryAtom] = []
        for _score, memory_id, revision, source_sha in scored:
            atom = self.storage.get(memory_id)
            if atom is None:
                continue
            # Never serve stale derived data. Revalidate against authoritative source.
            if atom.revision != revision or _source_sha256(atom) != source_sha:
                self.rebuild_space(memory_space_id, namespaces=namespaces, include_lifecycle=include_lifecycle)
                return self.search(
                    query,
                    memory_space_id=memory_space_id,
                    namespaces=namespaces,
                    include_lifecycle=include_lifecycle,
                    limit=limit,
                )
            result.append(atom)
            if len(result) >= limit:
                break
        return result

    def health(self) -> dict[str, Any]:
        with self._lock:
            try:
                with self._db() as c:
                    quick = c.execute("PRAGMA quick_check").fetchone()[0]
                    count = c.execute("SELECT COUNT(*) FROM derived_docs").fetchone()[0]
                return {
                    "status": "PASS" if quick == "ok" else "FAIL",
                    "index_version": _INDEX_VERSION,
                    "document_count": int(count),
                    "source_of_truth": "EXTERNAL_STORAGE",
                    "derived_only": True,
                    "rebuildable": True,
                }
            except sqlite3.DatabaseError as exc:
                return {"status": "FAIL", "error": str(exc), "derived_only": True, "rebuildable": True}


def source_sha256(atom: MemoryAtom) -> str:
    """Public helper used by preservation/conformance tests."""
    return _source_sha256(atom)
