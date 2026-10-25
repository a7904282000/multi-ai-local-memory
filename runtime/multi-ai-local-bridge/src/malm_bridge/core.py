from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import asdict
from typing import Any, Callable

from . import __version__
from .auth import AuthProvider, Principal
from .errors import Forbidden, IdempotencyConflict, InvalidRequest
from .policy import DefaultCapturePolicy
from .semantic import DerivedSemanticIndex
from .storage.base import StorageAdapter
from .state import BridgeStateStore, InMemoryBridgeStateStore
from .types import AuditEvent, ClientIdentity, MemoryAtom
from .validation import parse_client, parse_execution_context, parse_memory_space, require_dict, require_str, validate_version


class BridgeCore:
    def __init__(
        self,
        storage: StorageAdapter,
        auth: AuthProvider,
        policy: DefaultCapturePolicy | None = None,
        state: BridgeStateStore | None = None,
        change_notifier: Callable[[], None] | None = None,
        semantic_index: DerivedSemanticIndex | None = None,
    ):
        self.storage = storage
        self.auth = auth
        self.policy = policy or DefaultCapturePolicy()
        self.state = state or InMemoryBridgeStateStore()
        self.change_notifier = change_notifier
        self.semantic_index = semantic_index
        self._lock = threading.RLock()

    @staticmethod
    def _fingerprint(payload: Any) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @staticmethod
    def _audit_id() -> str:
        return f"evt_{uuid.uuid4().hex}"

    def _notify_storage_change(self, tx: str | None, client: ClientIdentity | None, session_id: str | None, turn_id: str | None) -> None:
        if self.change_notifier is None:
            return
        try:
            self.change_notifier()
        except Exception as exc:
            # A wakeup hint must never convert an already committed memory write into
            # a failed Capture response. Periodic reconciliation remains authoritative.
            try:
                self._audit(
                    "SYNC_NOTIFY_FAILED", tx, client, session_id, turn_id,
                    status="FAIL", metadata={"error": f"{type(exc).__name__}: {exc}"},
                )
            except Exception:
                pass

    def _audit(self, event: str, tx: str | None, client: ClientIdentity | None, session_id: str | None, turn_id: str | None, *, status: str = "PASS", metadata: dict | None = None, idem: str | None = None):
        self.storage.append_audit(AuditEvent(
            event_id=self._audit_id(), event=event, transaction_id=tx,
            client_id=client.client_id if client else None,
            session_id=session_id, turn_id=turn_id, status=status,
            metadata=metadata or {},
        ), idempotency_key=idem)

    def _authenticate(self, credential: str | None, client: ClientIdentity | None, transaction_id: str | None) -> Principal:
        principal = self.auth.authenticate(credential, client)
        self._audit("CLIENT_AUTHENTICATED", transaction_id, client, None, None, metadata={"client_type": client.client_type if client else None})
        return principal

    def health(self) -> dict[str, Any]:
        semantic = self.semantic_index.health() if self.semantic_index is not None else {"status":"DISABLED"}
        overall = "PASS" if semantic.get("status") in {"PASS", "DISABLED"} else "DEGRADED"
        return {
            "status": overall,
            "bridge_version": __version__,
            "contract_version": "1.0",
            "storage": self.storage.health(),
            "state": self.state.health(),
            "semantic_recall": semantic,
        }

    def capabilities(self) -> dict[str, Any]:
        c = self.storage.capabilities()
        return {
            "contract_version": "1.0",
            "bridge_version": __version__,
            "recall": True,
            "capture": True,
            "shared_memory_spaces": True,
            "cross_model_shared_memory": True,
            "cross_client_shared_memory": True,
            "intermediary_neutral": True,
            "session_close": True,
            "diagnostics": True,
            "raw_archive": c.raw_archive,
            "storage_adapter": c.adapter_name,
            "auth_mode": self.auth.__class__.__name__,
            "storage_capabilities": asdict(c),
            "derived_semantic_recall": self.semantic_index is not None,
            "durable_capture_classifier": True,
        }

    def recall(self, payload: dict[str, Any], credential: str | None) -> dict[str, Any]:
        validate_version(payload)
        tx = require_str(payload, "transaction_id")
        client = parse_client(payload)
        memory_space = parse_memory_space(payload)
        execution = parse_execution_context(payload)
        session_id = require_str(payload, "session_id")
        turn_id = require_str(payload, "turn_id")
        query = require_dict(payload.get("query"), "query")
        user_text = require_str(query, "user_text", allow_empty=True)
        scopes = query.get("scopes") or []
        max_items = query.get("max_items", 12)
        if not isinstance(scopes, list) or not all(isinstance(x, str) for x in scopes):
            raise InvalidRequest("query.scopes must be a string array", tx)
        if not isinstance(max_items, int) or not 0 <= max_items <= 100:
            raise InvalidRequest("query.max_items must be between 0 and 100", tx)

        principal = self._authenticate(credential, client, tx)
        if not principal.can_access_space(memory_space.space_id):
            raise Forbidden(f"Unauthorized memory space: {memory_space.space_id}", tx)
        unauthorized = [s for s in scopes if principal.scopes and s not in principal.scopes]
        if unauthorized:
            raise Forbidden(f"Unauthorized recall scopes: {unauthorized}", tx)

        self._audit("RECALL_STARTED", tx, client, session_id, turn_id)
        if self.semantic_index is not None:
            items = self.semantic_index.search(
                user_text,
                memory_space_id=memory_space.space_id,
                namespaces=scopes,
                include_lifecycle=["ACTIVE", "CONFLICT"],
                limit=max_items,
            )
            recall_mode = "derived-semantic"
        else:
            items = self.storage.search(user_text, {"memory_space_ids": [memory_space.space_id], "namespaces": scopes, "include_lifecycle": ["ACTIVE", "CONFLICT"]}, max_items)
            recall_mode = "storage-native"
        response_items = [{
            "memory_id": a.memory_id,
            "kind": a.kind,
            "content": a.content,
            "provenance": {
                "source_type": a.provenance.get("source_type", "local-memory"),
                "memory_space_id": a.memory_space_id,
                "revision": a.revision,
            },
        } for a in items]
        self._audit("RECALL_COMPLETED", tx, client, session_id, turn_id, metadata={"item_count": len(response_items), "recall_mode": recall_mode})
        return {
            "contract_version": "1.0",
            "transaction_id": tx,
            "memory_context_available": True,
            "items": response_items,
        }

    def capture(self, payload: dict[str, Any], credential: str | None) -> dict[str, Any]:
        validate_version(payload)
        tx = require_str(payload, "transaction_id")
        client = parse_client(payload)
        memory_space = parse_memory_space(payload)
        execution = parse_execution_context(payload)
        session_id = require_str(payload, "session_id")
        turn_id = require_str(payload, "turn_id")
        idem = require_str(payload, "idempotency_key")
        turn = require_dict(payload.get("turn"), "turn")
        user_text = require_str(turn, "user_text", allow_empty=True)
        assistant_text = require_str(turn, "assistant_text", allow_empty=True)
        injected_ids = turn.get("injected_memory_ids", [])
        explicit = turn.get("explicit_remember_request", False)
        if not isinstance(injected_ids, list) or not all(isinstance(x, str) for x in injected_ids):
            raise InvalidRequest("turn.injected_memory_ids must be a string array", tx)
        if not isinstance(explicit, bool):
            raise InvalidRequest("turn.explicit_remember_request must be boolean", tx)

        principal = self._authenticate(credential, client, tx)
        if not principal.can_access_space(memory_space.space_id):
            raise Forbidden(f"Unauthorized memory space: {memory_space.space_id}", tx)
        fp = self._fingerprint(payload)
        try:
            prior = self.state.get("capture", idem, fp)
        except IdempotencyConflict as exc:
            exc.transaction_id = tx
            raise
        if prior is not None:
            return json.loads(json.dumps(prior))

        self._audit("AFTER_RESPONSE", tx, client, session_id, turn_id)
        self._audit("CAPTURE_STARTED", tx, client, session_id, turn_id)
        decision = self.policy.classify(user_text, assistant_text, explicit)
        committed: list[str] = []
        conflicts: list[str] = []

        if decision.decision == "COMMIT":
            # Conservative core: explicit memories only. Semantic extraction arrives as a later pluggable policy/extractor.
            memory_id = f"mem_{uuid.uuid4().hex}"
            atom = MemoryAtom(
                memory_id=memory_id,
                kind=decision.kind or "memory",
                namespace="user",
                memory_space_id=memory_space.space_id,
                subject=memory_space.owner_id,
                key=decision.key or "memory",
                content=decision.content or user_text,
                sensitivity=decision.sensitivity,
                provenance={
                    "source_type": "capture",
                    "transaction_id": tx,
                    "client_id": client.client_id,
                    "client_type": client.client_type,
                    "client_instance_id": client.client_instance_id,
                    "memory_space_id": memory_space.space_id,
                    "surface": execution.surface,
                    "provider": execution.provider,
                    "product": execution.product,
                    "model": execution.model,
                    "agent_id": execution.agent_id,
                    "intermediary_chain": execution.intermediary_chain,
                },
            )
            self._audit("STORAGE_WRITE_STARTED", tx, client, session_id, turn_id, metadata={"memory_id": memory_id})
            stored = self.storage.commit(atom, idempotency_key=f"storage:{idem}")
            committed.append(stored.memory_id)
            self._audit("STORAGE_WRITE_COMMITTED", tx, client, session_id, turn_id, metadata={"memory_id": stored.memory_id})
            self._notify_storage_change(tx, client, session_id, turn_id)

        self._audit("CAPTURE_CLASSIFIED", tx, client, session_id, turn_id, metadata={"decision": decision.decision, "reason": decision.reason})
        result = {
            "contract_version": "1.0",
            "transaction_id": tx,
            "decision": decision.decision,
            "committed_memory_ids": committed,
            "conflict_ids": conflicts,
            "duplicate_count": 0,
        }
        try:
            self.state.put("capture", idem, fp, result)
        except IdempotencyConflict as exc:
            exc.transaction_id = tx
            raise
        return result

    def session_close(self, payload: dict[str, Any], credential: str | None) -> dict[str, Any]:
        validate_version(payload)
        tx = payload.get("transaction_id")
        client = parse_client(payload)
        session_id = require_str(payload, "session_id")
        idem = require_str(payload, "idempotency_key")
        self._authenticate(credential, client, tx)
        fp = self._fingerprint(payload)
        try:
            prior = self.state.get("session-close", idem, fp)
        except IdempotencyConflict as exc:
            exc.transaction_id = tx
            raise
        if prior is not None:
            return dict(prior)
        self._audit("SESSION_CLOSED", tx, client, session_id, None, idem=f"audit:{idem}")
        result = {"contract_version": "1.0", "session_id": session_id, "closed": True}
        try:
            self.state.put("session-close", idem, fp, result)
        except IdempotencyConflict as exc:
            exc.transaction_id = tx
            raise
        return dict(result)

    def diagnostics(self, credential: str | None, client: ClientIdentity | None = None) -> dict[str, Any]:
        principal = self._authenticate(credential, client, None)
        if not principal.admin:
            raise Forbidden("Diagnostics require local-admin capability")
        events = self.storage.audit_events()
        return {
            "bridge_version": __version__,
            "contract_version": "1.0",
            "storage": self.storage.health(),
            "state": self.state.health(),
            "semantic_recall": self.semantic_index.health() if self.semantic_index is not None else {"status":"DISABLED"},
            "audit_event_count": len(events),
            "last_event": events[-1].event if events else None,
        }
