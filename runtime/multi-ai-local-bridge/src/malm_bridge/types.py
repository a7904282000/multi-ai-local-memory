from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ClientIdentity:
    client_id: str
    client_type: str
    client_instance_id: str


@dataclass(slots=True)
class MemorySpaceIdentity:
    """Shared memory identity. Clients/models/agents are peers, not memory owners."""
    space_id: str
    owner_id: str
    kind: str = "personal"


@dataclass(slots=True)
class ExecutionContext:
    """Provenance only; never partitions shared memory."""
    surface: str = "unknown"
    provider: str | None = None
    product: str | None = None
    model: str | None = None
    agent_id: str | None = None
    intermediary_chain: list[dict[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class MemoryAtom:
    memory_id: str
    kind: str
    namespace: str
    memory_space_id: str
    subject: str
    key: str
    content: str
    verification_status: str = "VERIFIED"
    lifecycle_status: str = "ACTIVE"
    sensitivity: str = "NORMAL"
    confidence: float = 1.0
    provenance: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    revision: int = 1
    structured_value: Any = None
    tags: list[str] = field(default_factory=list)
    supersedes: str | None = None
    conflict_group_id: str | None = None
    expiry: str | None = None
    project_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AuditEvent:
    event_id: str
    event: str
    transaction_id: str | None
    client_id: str | None
    session_id: str | None
    turn_id: str | None
    timestamp: str = field(default_factory=utc_now)
    status: str = "PASS"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
