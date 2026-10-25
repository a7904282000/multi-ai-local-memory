from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Protocol

from .types import MemoryAtom
from .storage.base import StorageAdapter


@dataclass(slots=True)
class SyncPeerCapabilities:
    peer_id: str
    adapter_name: str
    adapter_version: str
    bidirectional: bool = True
    external_change_feed: bool = True


@dataclass(slots=True)
class ExternalMemoryChange:
    """A native memory-software edit normalized by its adapter.

    base_revision is the canonical revision the external edit was based on.
    0 means a new canonical atom.
    """
    change_id: str
    memory_space_id: str
    operation: str
    atom: MemoryAtom
    base_revision: int
    origin_peer_id: str


@dataclass(slots=True)
class ChangeBatch:
    changes: list[ExternalMemoryChange]
    next_cursor: str | None


@dataclass(slots=True)
class PushResult:
    applied: int
    skipped: int


class SyncPeerAdapter(Protocol):
    """Adapter boundary for any memory software that participates in two-way sync."""

    def sync_capabilities(self) -> SyncPeerCapabilities: ...
    def pull_changes(self, memory_space_id: str, cursor: str | None, limit: int = 100) -> ChangeBatch: ...
    def push_atoms(self, memory_space_id: str, atoms: list[MemoryAtom], idempotency_key: str) -> PushResult: ...
    def sync_health(self) -> dict[str, Any]: ...


class MemorySyncCoordinator:
    """Canonical SSOT <-> arbitrary memory-software peers.

    The primary StorageAdapter remains authoritative. Peer adapters translate native
    formats to/from canonical MemoryAtom objects. Models, agents and clients never
    participate in storage-specific synchronization.
    """

    def __init__(self, primary: StorageAdapter):
        self.primary = primary

    @staticmethod
    def _atom_equivalent(a: MemoryAtom, b: MemoryAtom) -> bool:
        fields = ("kind", "namespace", "memory_space_id", "subject", "key", "content",
                  "verification_status", "lifecycle_status", "sensitivity")
        return all(getattr(a, f) == getattr(b, f) for f in fields)

    def _import_change(self, change: ExternalMemoryChange) -> tuple[str, str | None]:
        if change.operation != "UPSERT":
            raise ValueError(f"Unsupported sync operation: {change.operation}")
        if change.atom.memory_space_id != change.memory_space_id:
            raise ValueError("Change memory_space_id does not match atom")

        local = self.primary.get(change.atom.memory_id)
        idem = f"sync-in:{change.origin_peer_id}:{change.change_id}"

        if local is None:
            if change.base_revision not in (0, 1):
                # The peer claims it edited a canonical object that this SSOT does not know.
                return "CONFLICT", None
            incoming = replace(change.atom, revision=1)
            stored = self.primary.commit(incoming, idem)
            return "IMPORTED", stored.memory_id

        if self._atom_equivalent(local, change.atom):
            return "NOOP", local.memory_id

        if change.base_revision == local.revision:
            # Storage owns the canonical revision increment; peer does not overwrite it.
            incoming = replace(
                change.atom,
                revision=local.revision,
                created_at=local.created_at,
                memory_space_id=local.memory_space_id,
                subject=local.subject,
            )
            stored = self.primary.commit(incoming, idem, expected_revision=local.revision)
            return "UPDATED", stored.memory_id

        # Concurrent/stale edit: preserve both versions and open an explicit conflict.
        # The conflict atom id is deterministic so replay after a crash (before the
        # runtime cursor is persisted) is idempotent and cannot create duplicate conflicts.
        conflict_seed = f"{change.origin_peer_id}\0{change.change_id}\0{change.atom.memory_id}"
        conflict_id = "mem_syncconf_" + hashlib.sha256(conflict_seed.encode("utf-8")).hexdigest()[:32]
        conflict_atom = replace(
            change.atom,
            memory_id=conflict_id,
            revision=1,
            lifecycle_status="ACTIVE",
            provenance={
                **change.atom.provenance,
                "source_type": "sync-peer-conflict",
                "origin_peer_id": change.origin_peer_id,
                "source_memory_id": change.atom.memory_id,
                "base_revision": change.base_revision,
            },
        )
        self.primary.commit(conflict_atom, idem)
        group = self.primary.open_conflict(
            [local.memory_id, conflict_id],
            {"source_peer_id": change.origin_peer_id},
            f"sync-conflict:{change.origin_peer_id}:{change.change_id}",
        )
        return "CONFLICT", group

    def _snapshot(self, memory_space_id: str) -> list[MemoryAtom]:
        return self.primary.search(
            "",
            {
                "memory_space_ids": [memory_space_id],
                "include_lifecycle": ["ACTIVE", "CONFLICT", "SUPERSEDED", "TOMBSTONED"],
            },
            10000,
        )

    def fan_in_peer(self, peer: SyncPeerAdapter, memory_space_id: str, cursor: str | None = None, *, limit: int = 1000) -> dict[str, Any]:
        """Import one durable change-feed page from one peer without fan-out."""
        caps = peer.sync_capabilities()
        if not caps.bidirectional or not caps.external_change_feed:
            raise ValueError(f"Peer {caps.peer_id} is not v1 bidirectional-sync capable")
        batch = peer.pull_changes(memory_space_id, cursor, limit=limit)
        stats = {"imported": 0, "updated": 0, "noop": 0, "conflicts": 0, "conflict_groups": []}
        for change in batch.changes:
            status, ref = self._import_change(change)
            key = {"IMPORTED":"imported", "UPDATED":"updated", "NOOP":"noop", "CONFLICT":"conflicts"}[status]
            stats[key] += 1
            if status == "CONFLICT" and ref:
                stats["conflict_groups"].append(ref)
        return {
            "peer_id": caps.peer_id,
            "memory_space_id": memory_space_id,
            "next_cursor": batch.next_cursor,
            "change_count": len(batch.changes),
            **stats,
        }

    def fan_out_peer(self, peer: SyncPeerAdapter, memory_space_id: str, atoms: list[MemoryAtom] | None = None) -> dict[str, Any]:
        """Push the final canonical snapshot to one peer."""
        caps = peer.sync_capabilities()
        if not caps.bidirectional:
            raise ValueError(f"Peer {caps.peer_id} is not v1 bidirectional-sync capable")
        atoms = self._snapshot(memory_space_id) if atoms is None else atoms
        digest = hashlib.sha256(json.dumps([a.to_dict() for a in atoms], sort_keys=True, default=str).encode()).hexdigest()
        r = peer.push_atoms(memory_space_id, atoms, f"sync-out:{caps.peer_id}:{digest}")
        return {"peer_id": caps.peer_id, "applied": r.applied, "skipped": r.skipped, "digest": digest}

    def sync_peer(self, peer: SyncPeerAdapter, memory_space_id: str, cursor: str | None = None) -> dict[str, Any]:
        caps = peer.sync_capabilities()
        if not caps.bidirectional or not caps.external_change_feed:
            raise ValueError(f"Peer {caps.peer_id} is not v1 bidirectional-sync capable")

        batch = peer.pull_changes(memory_space_id, cursor, limit=1000)
        imported = updated = noop = conflicts = 0
        conflict_groups: list[str] = []
        for change in batch.changes:
            status, ref = self._import_change(change)
            if status == "IMPORTED": imported += 1
            elif status == "UPDATED": updated += 1
            elif status == "NOOP": noop += 1
            elif status == "CONFLICT":
                conflicts += 1
                if ref: conflict_groups.append(ref)

        atoms = self._snapshot(memory_space_id)
        digest = hashlib.sha256(json.dumps([a.to_dict() for a in atoms], sort_keys=True, default=str).encode()).hexdigest()
        push = peer.push_atoms(memory_space_id, atoms, f"sync-out:{caps.peer_id}:{digest}")
        return {
            "peer_id": caps.peer_id,
            "memory_space_id": memory_space_id,
            "next_cursor": batch.next_cursor,
            "imported": imported,
            "updated": updated,
            "noop": noop,
            "conflicts": conflicts,
            "conflict_groups": conflict_groups,
            "pushed": push.applied,
            "push_skipped": push.skipped,
        }

    def sync_all(self, peers: list[SyncPeerAdapter], memory_space_id: str, cursors: dict[str, str | None] | None = None) -> dict[str, Any]:
        """Two-phase fan-in/fan-out.

        First import all peer changes into the SSOT. Then fan the final canonical snapshot
        back out to every peer. This is what allows Software A -> SSOT -> Software B.
        """
        cursors = dict(cursors or {})
        pull_results: dict[str, dict[str, Any]] = {}
        new_cursors: dict[str, str | None] = {}

        # Fan-in only: use a lightweight inline form of sync_peer without pushing yet.
        for peer in peers:
            caps = peer.sync_capabilities()
            batch = peer.pull_changes(memory_space_id, cursors.get(caps.peer_id), limit=1000)
            stats = {"imported": 0, "updated": 0, "noop": 0, "conflicts": 0, "conflict_groups": []}
            for change in batch.changes:
                status, ref = self._import_change(change)
                key = {"IMPORTED":"imported", "UPDATED":"updated", "NOOP":"noop", "CONFLICT":"conflicts"}[status]
                stats[key] += 1
                if status == "CONFLICT" and ref:
                    stats["conflict_groups"].append(ref)
            pull_results[caps.peer_id] = stats
            new_cursors[caps.peer_id] = batch.next_cursor

        # Fan-out final canonical state to every connected memory software.
        atoms = self._snapshot(memory_space_id)
        digest = hashlib.sha256(json.dumps([a.to_dict() for a in atoms], sort_keys=True, default=str).encode()).hexdigest()
        pushes = {}
        for peer in peers:
            caps = peer.sync_capabilities()
            r = peer.push_atoms(memory_space_id, atoms, f"sync-out:{caps.peer_id}:{digest}")
            pushes[caps.peer_id] = {"applied": r.applied, "skipped": r.skipped}

        return {"memory_space_id": memory_space_id, "pulls": pull_results, "pushes": pushes, "cursors": new_cursors}
