from __future__ import annotations

import copy
import hashlib
import json
import threading
import uuid
from dataclasses import replace
from typing import Any

from ..errors import IdempotencyConflict
from ..types import AuditEvent, MemoryAtom, utc_now
from .base import StorageCapabilities


class InMemoryStorage:
    """Reference adapter used by conformance tests. Not intended as durable production storage."""

    def __init__(self):
        self._atoms: dict[str, MemoryAtom] = {}
        self._audit: list[AuditEvent] = []
        self._idem: dict[str, tuple[str, Any]] = {}
        self._lock = threading.RLock()

    def capabilities(self) -> StorageCapabilities:
        return StorageCapabilities(
            adapter_name="in-memory-reference",
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
        return {"status": "PASS", "atom_count": len(self._atoms), "audit_count": len(self._audit)}

    @staticmethod
    def _fingerprint(payload: Any) -> str:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _idem_get(self, key: str, payload: Any):
        fp = self._fingerprint(payload)
        if key not in self._idem:
            return None, fp
        stored_fp, result = self._idem[key]
        if stored_fp != fp:
            raise IdempotencyConflict()
        return copy.deepcopy(result), fp

    def _idem_put(self, key: str, fp: str, result: Any):
        self._idem[key] = (fp, copy.deepcopy(result))

    def search(self, query: str, filters: dict[str, Any], limit: int) -> list[MemoryAtom]:
        q = query.casefold().strip()
        namespaces = filters.get("namespaces") or []
        memory_space_ids = filters.get("memory_space_ids") or []
        include_lifecycle = set(filters.get("include_lifecycle") or ["ACTIVE", "CONFLICT"])
        if not isinstance(namespaces, list) or not all(isinstance(x, str) for x in namespaces):
            raise ValueError("filters.namespaces must be a string array")
        if not isinstance(memory_space_ids, list) or not all(isinstance(x, str) for x in memory_space_ids):
            raise ValueError("filters.memory_space_ids must be a string array")
        with self._lock:
            atoms = [
                copy.deepcopy(a) for a in self._atoms.values()
                if a.lifecycle_status in include_lifecycle
                and (not memory_space_ids or a.memory_space_id in memory_space_ids)
                and (not namespaces or a.namespace in namespaces)
                and (not q or q in f"{a.subject} {a.key} {a.content}".casefold())
            ]
        atoms.sort(key=lambda a: (a.updated_at, a.memory_id), reverse=True)
        return atoms[:limit]

    def get(self, memory_id: str) -> MemoryAtom | None:
        with self._lock:
            atom = self._atoms.get(memory_id)
            return copy.deepcopy(atom) if atom else None

    def commit(self, atom: MemoryAtom, idempotency_key: str, expected_revision: int | None = None) -> MemoryAtom:
        payload = {"op": "commit", "atom": atom.to_dict(), "expected_revision": expected_revision}
        with self._lock:
            prior, fp = self._idem_get(idempotency_key, payload)
            if prior is not None:
                return prior
            current = self._atoms.get(atom.memory_id)
            if expected_revision is not None:
                if current is None or current.revision != expected_revision:
                    raise RuntimeError("REVISION_CONFLICT")
            if current:
                atom = replace(atom, revision=current.revision + 1, created_at=current.created_at, updated_at=utc_now())
            self._atoms[atom.memory_id] = copy.deepcopy(atom)
            result = copy.deepcopy(atom)
            self._idem_put(idempotency_key, fp, result)
            return result

    def supersede(self, old_memory_id: str, new_atom: MemoryAtom, idempotency_key: str, expected_revision: int | None = None) -> MemoryAtom:
        payload = {"op": "supersede", "old": old_memory_id, "new": new_atom.to_dict(), "expected_revision": expected_revision}
        with self._lock:
            prior, fp = self._idem_get(idempotency_key, payload)
            if prior is not None:
                return prior
            old = self._atoms.get(old_memory_id)
            if old is None:
                raise KeyError("NOT_FOUND")
            if expected_revision is not None and old.revision != expected_revision:
                raise RuntimeError("REVISION_CONFLICT")
            self._atoms[old_memory_id] = replace(old, lifecycle_status="SUPERSEDED", updated_at=utc_now(), revision=old.revision + 1)
            new_atom = replace(new_atom, supersedes=old_memory_id)
            self._atoms[new_atom.memory_id] = copy.deepcopy(new_atom)
            result = copy.deepcopy(new_atom)
            self._idem_put(idempotency_key, fp, result)
            return result

    def open_conflict(self, atom_ids: list[str], metadata: dict[str, Any], idempotency_key: str) -> str:
        payload = {"op": "conflict", "atom_ids": atom_ids, "metadata": metadata}
        with self._lock:
            prior, fp = self._idem_get(idempotency_key, payload)
            if prior is not None:
                return prior
            gid = metadata.get("conflict_group_id") or f"conf_{uuid.uuid4().hex}"
            for atom_id in atom_ids:
                atom = self._atoms.get(atom_id)
                if atom:
                    self._atoms[atom_id] = replace(atom, lifecycle_status="CONFLICT", conflict_group_id=gid, updated_at=utc_now(), revision=atom.revision + 1)
            self._idem_put(idempotency_key, fp, gid)
            return gid

    def append_audit(self, event: AuditEvent, idempotency_key: str | None = None) -> None:
        with self._lock:
            if idempotency_key:
                payload = {"op": "audit", "event": event.to_dict()}
                prior, fp = self._idem_get(idempotency_key, payload)
                if prior is not None:
                    return
                self._audit.append(copy.deepcopy(event))
                self._idem_put(idempotency_key, fp, True)
            else:
                self._audit.append(copy.deepcopy(event))

    def audit_events(self) -> list[AuditEvent]:
        with self._lock:
            return copy.deepcopy(self._audit)
