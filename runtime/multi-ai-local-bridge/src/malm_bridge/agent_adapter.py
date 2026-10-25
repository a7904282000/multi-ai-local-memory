from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import BridgeClient, BridgeClientError


SECURITY_STATUSES = {400, 401, 403}


class AgentMemorySecurityError(RuntimeError):
    """A security/contract failure that must block the agent turn."""


@dataclass(slots=True)
class AgentTurnHandle:
    transaction_id: str
    session_id: str
    turn_id: str
    user_text: str
    injected_memory_ids: list[str]
    memory_context_available: bool


@dataclass(slots=True)
class AgentRecallResult:
    handle: AgentTurnHandle
    prepend_context: str
    memory_context_available: bool


def format_recall_context(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = [f"{i}. [{x.get('kind', 'memory')}] {x.get('content', '')}" for i, x in enumerate(items, 1)]
    return "<relevant-local-memory>\n" + "\n".join(lines) + "\n</relevant-local-memory>"


class JsonCaptureOutbox:
    """Small durable delivery queue for agent runtimes.

    The Bridge remains the idempotency authority; this queue only preserves delivery
    across local adapter/runtime restarts.
    """

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def save(self, rows: list[dict[str, Any]]) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
                f.write("\n")
            try:
                os.chmod(tmp_name, 0o600)
            except OSError:
                pass
            os.replace(tmp_name, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    def enqueue(self, row: dict[str, Any]) -> None:
        rows = self.load()
        idem = row["idempotency_key"]
        if not any(x.get("idempotency_key") == idem for x in rows):
            rows.append(row)
            self.save(rows)


class AgentMemoryAdapter:
    """Runtime-neutral agent/intermediary adapter over the stable Client Contract.

    Runtime wrappers only map their own hooks/session identifiers to before_turn and
    after_turn. OpenClaw is one such wrapper; it is not required by this class.
    """

    def __init__(self, client: BridgeClient, *, outbox_path: str | os.PathLike[str]):
        self.client = client
        self.outbox = JsonCaptureOutbox(outbox_path)

    @staticmethod
    def _is_security_failure(exc: BridgeClientError) -> bool:
        return exc.status in SECURITY_STATUSES

    def flush_outbox(self) -> dict[str, int]:
        rows = self.outbox.load()
        keep: list[dict[str, Any]] = []
        sent = 0
        for index, row in enumerate(rows):
            try:
                self.client.capture(
                    row["user_text"],
                    row["assistant_text"],
                    session_id=row["session_id"],
                    turn_id=row["turn_id"],
                    transaction_id=row["transaction_id"],
                    injected_memory_ids=row.get("injected_memory_ids", []),
                    explicit_remember_request=bool(row.get("explicit_remember_request", False)),
                    idempotency_key=row["idempotency_key"],
                )
                sent += 1
            except BridgeClientError as exc:
                keep.append(row)
                if self._is_security_failure(exc):
                    # A credential/config failure cannot self-heal by hammering the Bridge.
                    keep.extend(rows[index + 1 :])
                    break
        self.outbox.save(keep)
        return {"sent": sent, "remaining": len(keep)}

    def before_turn(
        self,
        user_text: str,
        *,
        session_id: str,
        turn_id: str | None = None,
        transaction_id: str | None = None,
        scopes: list[str] | None = None,
        max_items: int = 12,
    ) -> AgentRecallResult:
        tx = transaction_id or str(uuid.uuid4())
        turn = turn_id or tx
        try:
            recalled = self.client.recall(
                user_text,
                session_id=session_id,
                turn_id=turn,
                transaction_id=tx,
                scopes=scopes or ["user", "project"],
                max_items=max_items,
            )
        except BridgeClientError as exc:
            if self._is_security_failure(exc):
                raise AgentMemorySecurityError(str(exc)) from exc
            handle = AgentTurnHandle(tx, session_id, turn, user_text, [], False)
            return AgentRecallResult(handle, "", False)

        items = recalled.get("items") or []
        ids = [x.get("memory_id") for x in items if x.get("memory_id")]
        available = bool(recalled.get("memory_context_available", True))
        handle = AgentTurnHandle(tx, session_id, turn, user_text, ids, available)
        return AgentRecallResult(handle, format_recall_context(items), available)

    def after_turn(
        self,
        handle: AgentTurnHandle,
        assistant_text: str,
        *,
        explicit_remember_request: bool = False,
    ) -> dict[str, Any]:
        row = {
            "transaction_id": handle.transaction_id,
            "session_id": handle.session_id,
            "turn_id": handle.turn_id,
            "idempotency_key": f"capture:{handle.transaction_id}",
            "user_text": handle.user_text,
            "assistant_text": assistant_text,
            "injected_memory_ids": list(handle.injected_memory_ids),
            "explicit_remember_request": bool(explicit_remember_request),
        }
        self.outbox.enqueue(row)
        result = self.flush_outbox()
        return {"queued": result["remaining"] > 0, **result}
