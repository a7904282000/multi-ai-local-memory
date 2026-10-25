from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..errors import IdempotencyConflict
from ..types import AuditEvent, MemoryAtom, utc_now
from .base import StorageCapabilities


class SQLiteStorageAdapter:
    """Durable transactional reference backend for the stable Storage Contract."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=FULL")
        return c

    @contextmanager
    def _db(self):
        c = self._connect()
        try:
            yield c
        finally:
            c.close()

    def _init_db(self) -> None:
        with self._db() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS atoms (
                    memory_id TEXT PRIMARY KEY,
                    memory_space_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    lifecycle_status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_atoms_space_ns_lifecycle
                    ON atoms(memory_space_id, namespace, lifecycle_status);
                CREATE INDEX IF NOT EXISTS idx_atoms_updated
                    ON atoms(updated_at DESC, memory_id DESC);

                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS idempotency (
                    idem_key TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    result_type TEXT NOT NULL,
                    result_json TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _fingerprint(payload: Any) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _atom_from_json(raw: str) -> MemoryAtom:
        return MemoryAtom(**json.loads(raw))

    @staticmethod
    def _event_from_json(raw: str) -> AuditEvent:
        return AuditEvent(**json.loads(raw))

    @staticmethod
    def _atom_json(atom: MemoryAtom) -> str:
        return json.dumps(atom.to_dict(), ensure_ascii=False, sort_keys=True)

    def _idem_get(self, c: sqlite3.Connection, key: str, fingerprint: str):
        row = c.execute("SELECT fingerprint,result_type,result_json FROM idempotency WHERE idem_key=?", (key,)).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != fingerprint:
            raise IdempotencyConflict()
        result = json.loads(row["result_json"])
        if row["result_type"] == "atom":
            return MemoryAtom(**result)
        return result

    def _idem_put(self, c: sqlite3.Connection, key: str, fingerprint: str, result_type: str, result: Any) -> None:
        if isinstance(result, MemoryAtom):
            value = result.to_dict()
        else:
            value = result
        c.execute(
            "INSERT INTO idempotency(idem_key,fingerprint,result_type,result_json) VALUES(?,?,?,?)",
            (key, fingerprint, result_type, json.dumps(value, ensure_ascii=False, sort_keys=True)),
        )

    def _upsert_atom(self, c: sqlite3.Connection, atom: MemoryAtom) -> None:
        c.execute(
            """
            INSERT INTO atoms(memory_id,memory_space_id,namespace,lifecycle_status,updated_at,payload_json)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(memory_id) DO UPDATE SET
                memory_space_id=excluded.memory_space_id,
                namespace=excluded.namespace,
                lifecycle_status=excluded.lifecycle_status,
                updated_at=excluded.updated_at,
                payload_json=excluded.payload_json
            """,
            (atom.memory_id, atom.memory_space_id, atom.namespace, atom.lifecycle_status, atom.updated_at, self._atom_json(atom)),
        )

    def capabilities(self) -> StorageCapabilities:
        return StorageCapabilities(
            adapter_name="sqlite",
            adapter_version="1.0",
            transactional_writes=True,
            compare_and_swap=True,
            full_text_search=True,
            semantic_search=False,
            raw_archive=False,
            audit_log=True,
            encryption_at_rest=False,
        )

    def health(self) -> dict[str, Any]:
        try:
            with self._db() as c:
                atoms = c.execute("SELECT COUNT(*) FROM atoms").fetchone()[0]
                audit = c.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
            return {"status":"PASS","adapter":"sqlite","atom_count":atoms,"audit_count":audit,"db_path":str(self.db_path)}
        except sqlite3.Error as exc:
            return {"status":"FAIL","adapter":"sqlite","error":str(exc)}

    def search(self, query: str, filters: dict[str, Any], limit: int) -> list[MemoryAtom]:
        q = query.casefold().strip()
        namespaces = filters.get("namespaces") or []
        spaces = filters.get("memory_space_ids") or []
        lifecycle = filters.get("include_lifecycle") or ["ACTIVE", "CONFLICT"]
        if not isinstance(namespaces, list) or not all(isinstance(x, str) for x in namespaces):
            raise ValueError("filters.namespaces must be a string array")
        if not isinstance(spaces, list) or not all(isinstance(x, str) for x in spaces):
            raise ValueError("filters.memory_space_ids must be a string array")
        if not isinstance(lifecycle, list) or not all(isinstance(x, str) for x in lifecycle):
            raise ValueError("filters.include_lifecycle must be a string array")
        clauses, params = [], []
        if spaces:
            clauses.append("memory_space_id IN (%s)" % ",".join("?" for _ in spaces)); params.extend(spaces)
        if namespaces:
            clauses.append("namespace IN (%s)" % ",".join("?" for _ in namespaces)); params.extend(namespaces)
        if lifecycle:
            clauses.append("lifecycle_status IN (%s)" % ",".join("?" for _ in lifecycle)); params.extend(lifecycle)
        sql = "SELECT payload_json FROM atoms"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC, memory_id DESC"
        with self._lock, self._db() as c:
            atoms = [self._atom_from_json(r[0]) for r in c.execute(sql, params)]
        if q:
            atoms = [a for a in atoms if q in f"{a.subject} {a.key} {a.content}".casefold()]
        return copy.deepcopy(atoms[:limit])

    def get(self, memory_id: str) -> MemoryAtom | None:
        with self._lock, self._db() as c:
            row = c.execute("SELECT payload_json FROM atoms WHERE memory_id=?", (memory_id,)).fetchone()
            return self._atom_from_json(row[0]) if row else None

    def commit(self, atom: MemoryAtom, idempotency_key: str, expected_revision: int | None = None) -> MemoryAtom:
        payload = {"op":"commit","atom":atom.to_dict(),"expected_revision":expected_revision}
        fp = self._fingerprint(payload)
        with self._lock, self._db() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                prior = self._idem_get(c, idempotency_key, fp)
                if isinstance(prior, MemoryAtom):
                    c.execute("COMMIT"); return prior
                row = c.execute("SELECT payload_json FROM atoms WHERE memory_id=?", (atom.memory_id,)).fetchone()
                current = self._atom_from_json(row[0]) if row else None
                if expected_revision is not None and (current is None or current.revision != expected_revision):
                    raise RuntimeError("REVISION_CONFLICT")
                if current:
                    atom = replace(atom, revision=current.revision + 1, created_at=current.created_at, updated_at=utc_now())
                else:
                    atom = replace(atom, revision=max(1, atom.revision))
                self._upsert_atom(c, atom)
                self._idem_put(c, idempotency_key, fp, "atom", atom)
                c.execute("COMMIT")
                return copy.deepcopy(atom)
            except Exception:
                c.execute("ROLLBACK")
                raise

    def supersede(self, old_memory_id: str, new_atom: MemoryAtom, idempotency_key: str, expected_revision: int | None = None) -> MemoryAtom:
        payload = {"op":"supersede","old":old_memory_id,"new":new_atom.to_dict(),"expected_revision":expected_revision}
        fp = self._fingerprint(payload)
        with self._lock, self._db() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                prior = self._idem_get(c, idempotency_key, fp)
                if isinstance(prior, MemoryAtom):
                    c.execute("COMMIT"); return prior
                row = c.execute("SELECT payload_json FROM atoms WHERE memory_id=?", (old_memory_id,)).fetchone()
                if row is None:
                    raise KeyError("NOT_FOUND")
                old = self._atom_from_json(row[0])
                if expected_revision is not None and old.revision != expected_revision:
                    raise RuntimeError("REVISION_CONFLICT")
                old2 = replace(old, lifecycle_status="SUPERSEDED", updated_at=utc_now(), revision=old.revision + 1)
                new2 = replace(new_atom, supersedes=old_memory_id, revision=max(1, new_atom.revision))
                self._upsert_atom(c, old2); self._upsert_atom(c, new2)
                self._idem_put(c, idempotency_key, fp, "atom", new2)
                c.execute("COMMIT")
                return copy.deepcopy(new2)
            except Exception:
                c.execute("ROLLBACK")
                raise

    def open_conflict(self, atom_ids: list[str], metadata: dict[str, Any], idempotency_key: str) -> str:
        payload = {"op":"conflict","atom_ids":atom_ids,"metadata":metadata}
        fp = self._fingerprint(payload)
        with self._lock, self._db() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                prior = self._idem_get(c, idempotency_key, fp)
                if isinstance(prior, str):
                    c.execute("COMMIT"); return prior
                gid = metadata.get("conflict_group_id") or f"conf_{uuid.uuid4().hex}"
                for memory_id in atom_ids:
                    row = c.execute("SELECT payload_json FROM atoms WHERE memory_id=?", (memory_id,)).fetchone()
                    if row:
                        atom = self._atom_from_json(row[0])
                        self._upsert_atom(c, replace(atom, lifecycle_status="CONFLICT", conflict_group_id=gid, updated_at=utc_now(), revision=atom.revision+1))
                self._idem_put(c, idempotency_key, fp, "scalar", gid)
                c.execute("COMMIT")
                return gid
            except Exception:
                c.execute("ROLLBACK")
                raise

    def append_audit(self, event: AuditEvent, idempotency_key: str | None = None) -> None:
        with self._lock, self._db() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                if idempotency_key:
                    key = f"audit:{idempotency_key}"
                    payload = {"op":"audit","event":event.to_dict()}
                    fp = self._fingerprint(payload)
                    prior = self._idem_get(c, key, fp)
                    if prior is not None:
                        c.execute("COMMIT"); return
                c.execute("INSERT INTO audit(event_id,payload_json) VALUES(?,?)", (event.event_id, json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)))
                if idempotency_key:
                    self._idem_put(c, key, fp, "scalar", True)
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise

    def audit_events(self) -> list[AuditEvent]:
        with self._lock, self._db() as c:
            return [self._event_from_json(r[0]) for r in c.execute("SELECT payload_json FROM audit ORDER BY seq")]
