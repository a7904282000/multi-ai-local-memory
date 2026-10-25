from __future__ import annotations

from .errors import InvalidRequest, UnsupportedVersion
from .types import ClientIdentity, ExecutionContext, MemorySpaceIdentity

CONTRACT_VERSION = "1.0"


def require_dict(value, name: str) -> dict:
    if not isinstance(value, dict):
        raise InvalidRequest(f"{name} must be an object")
    return value


def require_str(obj: dict, key: str, *, allow_empty: bool = False) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or (not allow_empty and not value):
        raise InvalidRequest(f"{key} must be a non-empty string")
    return value


def validate_version(payload: dict) -> None:
    if payload.get("contract_version") != CONTRACT_VERSION:
        raise UnsupportedVersion(payload.get("contract_version"), payload.get("transaction_id"))


def parse_client(payload: dict) -> ClientIdentity:
    raw = require_dict(payload.get("client"), "client")
    return ClientIdentity(
        client_id=require_str(raw, "client_id"),
        client_type=require_str(raw, "client_type"),
        client_instance_id=require_str(raw, "client_instance_id"),
    )


def parse_memory_space(payload: dict) -> MemorySpaceIdentity:
    raw = require_dict(payload.get("memory_space"), "memory_space")
    kind = raw.get("kind", "personal")
    if not isinstance(kind, str) or not kind:
        raise InvalidRequest("memory_space.kind must be a non-empty string")
    return MemorySpaceIdentity(
        space_id=require_str(raw, "space_id"),
        owner_id=require_str(raw, "owner_id"),
        kind=kind,
    )


def parse_execution_context(payload: dict) -> ExecutionContext:
    raw = payload.get("execution_context") or {}
    if not isinstance(raw, dict):
        raise InvalidRequest("execution_context must be an object")
    chain = raw.get("intermediary_chain") or []
    if not isinstance(chain, list) or not all(isinstance(x, dict) for x in chain):
        raise InvalidRequest("execution_context.intermediary_chain must be an object array")
    def opt(name):
        v = raw.get(name)
        if v is not None and not isinstance(v, str):
            raise InvalidRequest(f"execution_context.{name} must be a string or null")
        return v
    surface = raw.get("surface", "unknown")
    if not isinstance(surface, str) or not surface:
        raise InvalidRequest("execution_context.surface must be a non-empty string")
    return ExecutionContext(
        surface=surface, provider=opt("provider"), product=opt("product"),
        model=opt("model"), agent_id=opt("agent_id"), intermediary_chain=chain,
    )
