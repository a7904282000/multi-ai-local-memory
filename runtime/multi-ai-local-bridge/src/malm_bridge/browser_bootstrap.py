from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .auth import SQLiteCredentialRegistry
from .errors import Forbidden, InvalidRequest
from .types import ClientIdentity


@dataclass(frozen=True, slots=True)
class BrowserBootstrapPolicy:
    allowed_origins: frozenset[str]
    memory_spaces: frozenset[str]
    default_memory_space: dict[str, str]
    scopes: frozenset[str] = frozenset({"user", "project"})
    allowed_client_types: frozenset[str] = frozenset({"chatgpt-web", "grok-web", "web-ai"})

    @classmethod
    def build(
        cls,
        *,
        allowed_origins: Iterable[str],
        memory_spaces: Iterable[str],
        scopes: Iterable[str] = ("user", "project"),
        allowed_client_types: Iterable[str] = ("chatgpt-web", "grok-web", "web-ai"),
        default_memory_space: dict[str, str] | None = None,
    ) -> "BrowserBootstrapPolicy":
        spaces = frozenset(memory_spaces)
        if not spaces:
            raise ValueError("Browser bootstrap requires at least one memory space")
        default = dict(default_memory_space or {})
        default.setdefault("space_id", sorted(spaces)[0])
        default.setdefault("owner_id", "local-user")
        default.setdefault("kind", "personal")
        if default["space_id"] not in spaces:
            raise ValueError("default_memory_space.space_id must be authorized")
        return cls(
            allowed_origins=frozenset(x.rstrip("/") for x in allowed_origins),
            memory_spaces=spaces,
            default_memory_space=default,
            scopes=frozenset(scopes),
            allowed_client_types=frozenset(allowed_client_types),
        )


class BrowserBootstrapController:
    """Trusted loopback control-plane for browser extension credential provisioning.

    Security model:
    - callable only from loopback HTTP requests;
    - requires an exact allow-listed browser-extension Origin;
    - credentials are bound to the claimed client identity and allowed memory spaces;
    - re-bootstrap rotates credentials for that exact client instance;
    - plaintext token is returned once and is never persisted by the bridge.
    """

    def __init__(self, registry: SQLiteCredentialRegistry, policy: BrowserBootstrapPolicy):
        self.registry = registry
        self.policy = policy

    @staticmethod
    def _is_loopback(remote_host: str | None) -> bool:
        return remote_host in {"127.0.0.1", "::1", "localhost"}

    def provision(self, payload: dict, *, origin: str | None, remote_host: str | None) -> dict:
        if not self._is_loopback(remote_host):
            raise Forbidden("Browser bootstrap is loopback-only")
        normalized_origin = (origin or "").rstrip("/")
        if not normalized_origin or normalized_origin not in self.policy.allowed_origins:
            raise Forbidden("Browser extension origin is not authorized")
        raw = payload.get("client")
        if not isinstance(raw, dict):
            raise InvalidRequest("client must be an object")
        try:
            client = ClientIdentity(
                client_id=str(raw["client_id"]),
                client_type=str(raw["client_type"]),
                client_instance_id=str(raw["client_instance_id"]),
            )
        except Exception as exc:
            raise InvalidRequest("client identity is incomplete") from exc
        if not client.client_id or not client.client_type or not client.client_instance_id:
            raise InvalidRequest("client identity fields must be non-empty")
        if client.client_type not in self.policy.allowed_client_types:
            raise Forbidden(f"Unsupported browser client_type: {client.client_type}")

        issued = self.registry.rotate_for_client(
            client,
            scopes=self.policy.scopes,
            memory_spaces=self.policy.memory_spaces,
            admin=False,
        )
        return {
            "status": "PASS",
            "contract_version": "1.0",
            "credential_id": issued["credential_id"],
            "credential": issued["token"],
            "authorized_memory_spaces": sorted(self.policy.memory_spaces),
            "authorized_scopes": sorted(self.policy.scopes),
            "default_memory_space": dict(self.policy.default_memory_space),
        }
