from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ..types import AuditEvent, MemoryAtom


@dataclass(slots=True)
class StorageCapabilities:
    adapter_name: str
    adapter_version: str
    transactional_writes: bool
    compare_and_swap: bool
    full_text_search: bool
    semantic_search: bool
    raw_archive: bool
    audit_log: bool
    encryption_at_rest: bool


class StorageAdapter(Protocol):
    def capabilities(self) -> StorageCapabilities: ...
    def health(self) -> dict[str, Any]: ...
    def search(self, query: str, filters: dict[str, Any], limit: int) -> list[MemoryAtom]: ...
    def get(self, memory_id: str) -> MemoryAtom | None: ...
    def commit(self, atom: MemoryAtom, idempotency_key: str, expected_revision: int | None = None) -> MemoryAtom: ...
    def supersede(self, old_memory_id: str, new_atom: MemoryAtom, idempotency_key: str, expected_revision: int | None = None) -> MemoryAtom: ...
    def open_conflict(self, atom_ids: list[str], metadata: dict[str, Any], idempotency_key: str) -> str: ...
    def append_audit(self, event: AuditEvent, idempotency_key: str | None = None) -> None: ...
    def audit_events(self) -> list[AuditEvent]: ...
