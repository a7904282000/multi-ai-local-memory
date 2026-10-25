from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from typing import Any

from ..sync import ChangeBatch, ExternalMemoryChange, PushResult, SyncPeerCapabilities
from ..types import MemoryAtom, utc_now


class ReferenceMemorySoftwarePeer:
    """Reference adapter used only to prove the any-memory-software sync contract."""

    def __init__(self, peer_id: str, adapter_name: str = "reference-memory-software"):
        self.peer_id = peer_id
        self.adapter_name = adapter_name
        self._atoms: dict[str, MemoryAtom] = {}
        self._changes: list[ExternalMemoryChange] = []
        self._push_idem: dict[str, str] = {}

    def sync_capabilities(self) -> SyncPeerCapabilities:
        return SyncPeerCapabilities(self.peer_id, self.adapter_name, "1.0", True, True)

    def sync_health(self) -> dict[str, Any]:
        return {"status":"PASS", "peer_id":self.peer_id, "atom_count":len(self._atoms), "pending_changes":len(self._changes)}

    def pull_changes(self, memory_space_id: str, cursor: str | None, limit: int = 100) -> ChangeBatch:
        start = int(cursor or 0)
        i = start
        eligible: list[ExternalMemoryChange] = []
        while i < len(self._changes) and len(eligible) < limit:
            change = self._changes[i]
            i += 1
            if change.memory_space_id == memory_space_id:
                eligible.append(change)
        # Cursor is the next global change index actually scanned. This prevents a
        # batch limit from skipping unseen changes.
        return ChangeBatch(copy.deepcopy(eligible), str(i))

    def push_atoms(self, memory_space_id: str, atoms: list[MemoryAtom], idempotency_key: str) -> PushResult:
        fp = hashlib.sha256(json.dumps([a.to_dict() for a in atoms], sort_keys=True, default=str).encode()).hexdigest()
        if idempotency_key in self._push_idem:
            if self._push_idem[idempotency_key] != fp:
                raise RuntimeError("IDEMPOTENCY_CONFLICT")
            return PushResult(0, len(atoms))
        applied = skipped = 0
        incoming_ids = set()
        for atom in atoms:
            if atom.memory_space_id != memory_space_id:
                continue
            incoming_ids.add(atom.memory_id)
            current = self._atoms.get(atom.memory_id)
            if current and current.to_dict() == atom.to_dict():
                skipped += 1
            else:
                self._atoms[atom.memory_id] = copy.deepcopy(atom)
                applied += 1
        self._push_idem[idempotency_key] = fp
        return PushResult(applied, skipped)

    # The methods below simulate a user or another application editing the native memory software.
    def external_create(self, atom: MemoryAtom) -> str:
        atom = replace(atom, revision=1, updated_at=utc_now())
        self._atoms[atom.memory_id] = copy.deepcopy(atom)
        cid = f"chg-{self.peer_id}-{len(self._changes)+1}"
        self._changes.append(ExternalMemoryChange(cid, atom.memory_space_id, "UPSERT", copy.deepcopy(atom), 0, self.peer_id))
        return cid

    def external_update(self, memory_id: str, *, content: str) -> str:
        current = self._atoms[memory_id]
        proposed = replace(current, content=content, updated_at=utc_now())
        self._atoms[memory_id] = copy.deepcopy(proposed)
        cid = f"chg-{self.peer_id}-{len(self._changes)+1}"
        self._changes.append(ExternalMemoryChange(cid, proposed.memory_space_id, "UPSERT", copy.deepcopy(proposed), current.revision, self.peer_id))
        return cid

    def get(self, memory_id: str) -> MemoryAtom | None:
        atom = self._atoms.get(memory_id)
        return copy.deepcopy(atom) if atom else None

    def all_atoms(self, memory_space_id: str) -> list[MemoryAtom]:
        return [copy.deepcopy(a) for a in self._atoms.values() if a.memory_space_id == memory_space_id]
