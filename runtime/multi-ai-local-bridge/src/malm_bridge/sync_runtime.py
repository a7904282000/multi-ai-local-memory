from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .sync import MemorySyncCoordinator, SyncPeerAdapter
from .types import utc_now


@dataclass(slots=True)
class RuntimePeerStatus:
    peer_id: str
    status: str = "UNPROVEN"
    last_success_at: str | None = None
    last_error_at: str | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    last_pull_count: int = 0
    last_push_applied: int = 0
    last_push_skipped: int = 0


@dataclass(slots=True)
class SyncCycleResult:
    started_at: str
    finished_at: str
    spaces: dict[str, Any] = field(default_factory=dict)
    peer_errors: dict[str, str] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "PASS" if not self.peer_errors else "DEGRADED"


class SyncRuntimeStateStore:
    """Durable runtime cursors/status, separate from recallable memory.

    Cursor state is committed only after a peer page has been imported successfully.
    If the process crashes before that commit, the page is replayed. The sync/import
    path is required to be idempotent, making replay safe.
    """

    def __init__(self, db_path: str | os.PathLike[str]):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init_db(self) -> None:
        c = self._connect()
        try:
            c.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS sync_cursors (
                    peer_id TEXT NOT NULL,
                    memory_space_id TEXT NOT NULL,
                    cursor TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(peer_id, memory_space_id)
                );
                CREATE TABLE IF NOT EXISTS peer_status (
                    peer_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    last_success_at TEXT,
                    last_error_at TEXT,
                    last_error TEXT,
                    consecutive_failures INTEGER NOT NULL DEFAULT 0,
                    last_pull_count INTEGER NOT NULL DEFAULT 0,
                    last_push_applied INTEGER NOT NULL DEFAULT 0,
                    last_push_skipped INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runtime_meta (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            c.commit()
        finally:
            c.close()

    def get_cursor(self, peer_id: str, memory_space_id: str) -> str | None:
        with self._lock:
            c = self._connect()
            try:
                row = c.execute(
                    "SELECT cursor FROM sync_cursors WHERE peer_id=? AND memory_space_id=?",
                    (peer_id, memory_space_id),
                ).fetchone()
                return None if row is None else row["cursor"]
            finally:
                c.close()

    def set_cursor(self, peer_id: str, memory_space_id: str, cursor: str | None) -> None:
        with self._lock:
            c = self._connect()
            try:
                c.execute(
                    """
                    INSERT INTO sync_cursors(peer_id,memory_space_id,cursor,updated_at)
                    VALUES(?,?,?,?)
                    ON CONFLICT(peer_id,memory_space_id) DO UPDATE SET
                      cursor=excluded.cursor,
                      updated_at=excluded.updated_at
                    """,
                    (peer_id, memory_space_id, cursor, utc_now()),
                )
                c.commit()
            finally:
                c.close()

    def record_peer_success(self, status: RuntimePeerStatus) -> None:
        status.status = "PASS"
        status.last_success_at = utc_now()
        status.last_error = None
        status.consecutive_failures = 0
        self._write_peer(status)

    def record_peer_failure(self, status: RuntimePeerStatus, exc: BaseException) -> None:
        status.status = "FAIL"
        status.last_error_at = utc_now()
        status.last_error = f"{type(exc).__name__}: {exc}"
        status.consecutive_failures += 1
        self._write_peer(status)

    def _write_peer(self, status: RuntimePeerStatus) -> None:
        with self._lock:
            c = self._connect()
            try:
                c.execute(
                    """
                    INSERT INTO peer_status(
                      peer_id,status,last_success_at,last_error_at,last_error,
                      consecutive_failures,last_pull_count,last_push_applied,
                      last_push_skipped,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(peer_id) DO UPDATE SET
                      status=excluded.status,
                      last_success_at=excluded.last_success_at,
                      last_error_at=excluded.last_error_at,
                      last_error=excluded.last_error,
                      consecutive_failures=excluded.consecutive_failures,
                      last_pull_count=excluded.last_pull_count,
                      last_push_applied=excluded.last_push_applied,
                      last_push_skipped=excluded.last_push_skipped,
                      updated_at=excluded.updated_at
                    """,
                    (
                        status.peer_id,
                        status.status,
                        status.last_success_at,
                        status.last_error_at,
                        status.last_error,
                        status.consecutive_failures,
                        status.last_pull_count,
                        status.last_push_applied,
                        status.last_push_skipped,
                        utc_now(),
                    ),
                )
                c.commit()
            finally:
                c.close()

    def set_meta(self, key: str, value: Any) -> None:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        with self._lock:
            c = self._connect()
            try:
                c.execute(
                    """
                    INSERT INTO runtime_meta(key,value_json,updated_at) VALUES(?,?,?)
                    ON CONFLICT(key) DO UPDATE SET
                      value_json=excluded.value_json,
                      updated_at=excluded.updated_at
                    """,
                    (key, payload, utc_now()),
                )
                c.commit()
            finally:
                c.close()

    def get_meta(self, key: str) -> Any:
        with self._lock:
            c = self._connect()
            try:
                row = c.execute("SELECT value_json FROM runtime_meta WHERE key=?", (key,)).fetchone()
                return None if row is None else json.loads(row["value_json"])
            finally:
                c.close()

    def health(self) -> dict[str, Any]:
        c = self._connect()
        try:
            cursors = c.execute("SELECT COUNT(*) FROM sync_cursors").fetchone()[0]
            peers = c.execute("SELECT COUNT(*) FROM peer_status").fetchone()[0]
            failing = c.execute("SELECT COUNT(*) FROM peer_status WHERE status='FAIL'").fetchone()[0]
            return {
                "status": "PASS" if failing == 0 else "DEGRADED",
                "state_store": "sqlite-sync-runtime",
                "cursor_count": cursors,
                "peer_count": peers,
                "failing_peer_count": failing,
                "db_path": str(self.db_path),
            }
        finally:
            c.close()


class PollingFilesystemWatcher:
    """Dependency-free, cross-platform recursive filesystem change detector.

    This is intentionally polling-based for the portable v1 baseline. The runtime only
    uses it as an early-wakeup signal; periodic reconciliation remains authoritative,
    so missed/merged filesystem notifications cannot lose data.
    """

    def __init__(self, roots: Iterable[str | os.PathLike[str]]):
        self.roots = tuple(Path(p).expanduser().resolve() for p in roots)
        self._signature = self._scan_signature()

    @staticmethod
    def _included(path: Path) -> bool:
        # Ignore transient atomic-write files. Managed .malm state files are included;
        # they may wake the runtime but cannot create a sync loop because reconciliation
        # and push idempotency are authoritative.
        return not path.name.endswith(".tmp") and ".tmp." not in path.name

    def _scan_signature(self) -> str:
        h = hashlib.sha256()
        for root in sorted(self.roots, key=lambda p: str(p)):
            h.update(str(root).encode("utf-8"))
            if not root.exists():
                h.update(b"<missing>")
                continue
            paths = [root] if root.is_file() else sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: str(p))
            for path in paths:
                if not self._included(path):
                    continue
                try:
                    st = path.stat()
                except FileNotFoundError:
                    continue
                h.update(str(path.relative_to(root) if root.is_dir() else path.name).encode("utf-8"))
                h.update(str(st.st_mtime_ns).encode("ascii"))
                h.update(str(st.st_size).encode("ascii"))
        return h.hexdigest()

    def changed(self) -> bool:
        current = self._scan_signature()
        if current == self._signature:
            return False
        self._signature = current
        return True

    def reset(self) -> None:
        self._signature = self._scan_signature()


class ProductionSyncRuntime:
    """Always-on bidirectional synchronization runtime.

    Design properties:
    - durable per-peer/per-space cursors;
    - startup reconciliation after downtime;
    - periodic reconciliation even when filesystem events are missed;
    - filesystem-change early wakeup for local memory software such as Obsidian;
    - peer failure isolation;
    - deterministic replay/idempotency across crashes;
    - no direct model/client participation in storage synchronization.
    """

    def __init__(
        self,
        coordinator: MemorySyncCoordinator,
        peers: list[SyncPeerAdapter],
        memory_space_ids: list[str],
        state: SyncRuntimeStateStore,
        *,
        sync_interval_seconds: float = 5.0,
        watch_poll_seconds: float = 0.25,
        page_limit: int = 1000,
        watch_paths: dict[str, list[str | os.PathLike[str]]] | None = None,
        primary_watch_paths: list[str | os.PathLike[str]] | None = None,
    ):
        if not memory_space_ids:
            raise ValueError("At least one memory_space_id is required")
        if sync_interval_seconds <= 0 or watch_poll_seconds <= 0 or page_limit <= 0:
            raise ValueError("Runtime intervals/page_limit must be positive")
        self.coordinator = coordinator
        self.peers = list(peers)
        self.memory_space_ids = list(dict.fromkeys(memory_space_ids))
        self.state = state
        self.sync_interval_seconds = float(sync_interval_seconds)
        self.watch_poll_seconds = float(watch_poll_seconds)
        self.page_limit = int(page_limit)
        self._cycle_lock = threading.RLock()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._peer_status: dict[str, RuntimePeerStatus] = {}
        self._last_cycle: SyncCycleResult | None = None

        explicit = watch_paths or {}
        self._watchers: dict[str, PollingFilesystemWatcher] = {}

        # Watch the primary SSOT too. This is essential when Obsidian is the default
        # primary: a human edit is not a peer change-feed event, but it must wake the
        # runtime so the updated canonical snapshot fans out to every other peer/model.
        primary_roots = list(primary_watch_paths or [])
        if not primary_roots:
            managed_root = getattr(self.coordinator.primary, "managed_root", None)
            if managed_root is not None:
                primary_roots = [managed_root]
            else:
                db_path = getattr(self.coordinator.primary, "db_path", None)
                if db_path is not None:
                    db_path = Path(db_path)
                    primary_roots = [db_path, Path(str(db_path) + "-wal")]
        if primary_roots:
            self._watchers["__primary__"] = PollingFilesystemWatcher(primary_roots)

        for peer in self.peers:
            caps = peer.sync_capabilities()
            self._peer_status[caps.peer_id] = RuntimePeerStatus(caps.peer_id)
            roots = list(explicit.get(caps.peer_id, []))
            if not roots:
                managed_root = getattr(peer, "managed_root", None)
                if managed_root is not None:
                    roots = [managed_root]
            if roots:
                self._watchers[caps.peer_id] = PollingFilesystemWatcher(roots)

    def _pull_peer_pages(self, peer: SyncPeerAdapter, memory_space_id: str) -> dict[str, Any]:
        caps = peer.sync_capabilities()
        cursor = self.state.get_cursor(caps.peer_id, memory_space_id)
        totals = {"imported": 0, "updated": 0, "noop": 0, "conflicts": 0, "conflict_groups": [], "change_count": 0}
        seen_cursors: set[str | None] = {cursor}

        while True:
            result = self.coordinator.fan_in_peer(
                peer,
                memory_space_id,
                cursor,
                limit=self.page_limit,
            )
            next_cursor = result["next_cursor"]
            for key in ("imported", "updated", "noop", "conflicts", "change_count"):
                totals[key] += int(result.get(key, 0))
            totals["conflict_groups"].extend(result.get("conflict_groups", []))

            # Persist only after successful import of this page. A crash before this
            # write replays the page; deterministic/import idempotency makes that safe.
            self.state.set_cursor(caps.peer_id, memory_space_id, next_cursor)

            if result["change_count"] < self.page_limit:
                cursor = next_cursor
                break
            if next_cursor == cursor or next_cursor in seen_cursors:
                raise RuntimeError(f"Non-advancing sync cursor from peer {caps.peer_id}")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        totals["next_cursor"] = cursor
        return totals

    def run_once(self) -> SyncCycleResult:
        with self._cycle_lock:
            started = utc_now()
            cycle = SyncCycleResult(started_at=started, finished_at=started)
            failed_peers: dict[str, BaseException] = {}

            # Metrics describe the complete cycle, not only the last memory space.
            for status in self._peer_status.values():
                status.last_pull_count = 0
                status.last_push_applied = 0
                status.last_push_skipped = 0

            for space_id in self.memory_space_ids:
                space_result: dict[str, Any] = {"pulls": {}, "pushes": {}}

                # Fan-in with peer isolation. One broken memory application must not
                # prevent the remaining peers from converging through the SSOT.
                for peer in self.peers:
                    caps = peer.sync_capabilities()
                    status = self._peer_status[caps.peer_id]
                    try:
                        pull = self._pull_peer_pages(peer, space_id)
                        status.last_pull_count += int(pull["change_count"])
                        space_result["pulls"][caps.peer_id] = pull
                    except Exception as exc:  # boundary isolation is intentional
                        failed_peers.setdefault(caps.peer_id, exc)
                        cycle.peer_errors[f"{space_id}:{caps.peer_id}:pull"] = f"{type(exc).__name__}: {exc}"
                        space_result["pulls"][caps.peer_id] = {"status": "FAIL", "error": str(exc)}

                # Fan-out the final canonical state. Pull failure does not necessarily
                # mean push is impossible, so each direction is independently isolated.
                atoms = self.coordinator._snapshot(space_id)
                for peer in self.peers:
                    caps = peer.sync_capabilities()
                    status = self._peer_status[caps.peer_id]
                    try:
                        push = self.coordinator.fan_out_peer(peer, space_id, atoms)
                        status.last_push_applied += int(push["applied"])
                        status.last_push_skipped += int(push["skipped"])
                        space_result["pushes"][caps.peer_id] = push
                    except Exception as exc:  # boundary isolation is intentional
                        failed_peers.setdefault(caps.peer_id, exc)
                        cycle.peer_errors[f"{space_id}:{caps.peer_id}:push"] = f"{type(exc).__name__}: {exc}"
                        space_result["pushes"][caps.peer_id] = {"status": "FAIL", "error": str(exc)}

                cycle.spaces[space_id] = space_result

            # A peer is PASS only if every configured memory-space/direction succeeded.
            for peer_id, status in self._peer_status.items():
                if peer_id in failed_peers:
                    self.state.record_peer_failure(status, failed_peers[peer_id])
                else:
                    self.state.record_peer_success(status)

            cycle.finished_at = utc_now()
            self._last_cycle = cycle
            self.state.set_meta("last_cycle", {
                "started_at": cycle.started_at,
                "finished_at": cycle.finished_at,
                "status": cycle.status,
                "peer_errors": cycle.peer_errors,
            })
            # Clear only a previous top-level daemon exception. Per-peer degradation is
            # represented by last_cycle/peer_status and must not poison runtime forever.
            self.state.set_meta("runtime_error", None)
            # Do NOT reset watcher baselines here. A human may edit a watched file while
            # this cycle is running; resetting after fan-out could absorb that edit and
            # lose the wakeup. Self-generated writes are allowed to cause one extra
            # reconciliation cycle; storage/push idempotency makes that harmless.
            return cycle

    def notify(self) -> None:
        """Wake the daemon after an internal Bridge commit or external integration event."""
        self._wake.set()

    def _filesystem_changed(self) -> bool:
        changed = False
        for watcher in self._watchers.values():
            try:
                if watcher.changed():
                    changed = True
            except OSError:
                # Periodic reconciliation remains authoritative; watcher errors are not
                # data-loss conditions and will be retried on the next poll.
                changed = True
        return changed

    def _loop(self) -> None:
        next_periodic = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            due = now >= next_periodic
            changed = self._filesystem_changed()
            explicit = self._wake.is_set()
            if due or changed or explicit:
                self._wake.clear()
                try:
                    self.run_once()
                except Exception as exc:
                    # A top-level bug must not silently kill the daemon. Persist a safe
                    # diagnostic and keep retrying; peer-specific errors are isolated inside.
                    self.state.set_meta("runtime_error", {
                        "at": utc_now(),
                        "error": f"{type(exc).__name__}: {exc}",
                    })
                next_periodic = time.monotonic() + self.sync_interval_seconds
            self._stop.wait(self.watch_poll_seconds)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._wake.set()  # startup reconciliation recovers changes made while offline
        self._thread = threading.Thread(target=self._loop, name="malm-sync-runtime", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread:
            thread.join(timeout)
            if thread.is_alive():
                raise RuntimeError("Sync runtime did not stop within timeout")

    def health(self) -> dict[str, Any]:
        alive = bool(self._thread and self._thread.is_alive())
        last = self.state.get_meta("last_cycle")
        runtime_error = self.state.get_meta("runtime_error")
        return {
            "status": "PASS" if alive and not runtime_error else ("STOPPED" if not alive else "DEGRADED"),
            "running": alive,
            "memory_space_ids": list(self.memory_space_ids),
            "peer_ids": [p.sync_capabilities().peer_id for p in self.peers],
            "watched_sources": sorted(self._watchers),
            "watched_peer_ids": sorted(k for k in self._watchers if k != "__primary__"),
            "primary_watched": "__primary__" in self._watchers,
            "last_cycle": last,
            "runtime_error": runtime_error,
            "state": self.state.health(),
        }
