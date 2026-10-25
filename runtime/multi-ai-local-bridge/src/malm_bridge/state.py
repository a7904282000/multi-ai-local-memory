from __future__ import annotations

import copy
import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from .errors import IdempotencyConflict


class BridgeStateStore(Protocol):
    def get(self, namespace: str, key: str, fingerprint: str) -> dict[str, Any] | None: ...
    def put(self, namespace: str, key: str, fingerprint: str, result: dict[str, Any]) -> None: ...
    def health(self) -> dict[str, Any]: ...


class InMemoryBridgeStateStore:
    def __init__(self):
        self._data: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def get(self, namespace: str, key: str, fingerprint: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._data.get((namespace, key))
            if row is None:
                return None
            old_fp, result = row
            if old_fp != fingerprint:
                raise IdempotencyConflict()
            return copy.deepcopy(result)

    def put(self, namespace: str, key: str, fingerprint: str, result: dict[str, Any]) -> None:
        with self._lock:
            row = self._data.get((namespace, key))
            if row is not None and row[0] != fingerprint:
                raise IdempotencyConflict()
            self._data[(namespace, key)] = (fingerprint, copy.deepcopy(result))

    def health(self) -> dict[str, Any]:
        return {"status":"PASS","state_store":"memory","entry_count":len(self._data)}


class SQLiteBridgeStateStore:
    """Durable bridge-level operation state.

    This is intentionally separate from user memory storage. It prevents capture/session
    retries from creating duplicates across daemon restarts without polluting recallable
    memory or coupling the Bridge Core to a specific StorageAdapter.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._db() as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS bridge_state (
                    namespace TEXT NOT NULL,
                    idem_key TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    PRIMARY KEY(namespace, idem_key)
                )
            """)

    @contextmanager
    def _db(self):
        c = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=FULL")
            yield c
        finally:
            c.close()

    def get(self, namespace: str, key: str, fingerprint: str) -> dict[str, Any] | None:
        with self._lock, self._db() as c:
            row = c.execute(
                "SELECT fingerprint,result_json FROM bridge_state WHERE namespace=? AND idem_key=?",
                (namespace, key),
            ).fetchone()
            if row is None:
                return None
            if row["fingerprint"] != fingerprint:
                raise IdempotencyConflict()
            return json.loads(row["result_json"])

    def put(self, namespace: str, key: str, fingerprint: str, result: dict[str, Any]) -> None:
        with self._lock, self._db() as c:
            c.execute("BEGIN IMMEDIATE")
            try:
                row = c.execute(
                    "SELECT fingerprint FROM bridge_state WHERE namespace=? AND idem_key=?",
                    (namespace, key),
                ).fetchone()
                if row is not None:
                    if row["fingerprint"] != fingerprint:
                        raise IdempotencyConflict()
                    c.execute("COMMIT")
                    return
                c.execute(
                    "INSERT INTO bridge_state(namespace,idem_key,fingerprint,result_json) VALUES(?,?,?,?)",
                    (namespace, key, fingerprint, json.dumps(result, ensure_ascii=False, sort_keys=True)),
                )
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise

    def health(self) -> dict[str, Any]:
        try:
            with self._db() as c:
                n = c.execute("SELECT COUNT(*) FROM bridge_state").fetchone()[0]
            return {"status":"PASS","state_store":"sqlite","entry_count":n,"db_path":str(self.db_path)}
        except sqlite3.Error as exc:
            return {"status":"FAIL","state_store":"sqlite","error":str(exc)}
