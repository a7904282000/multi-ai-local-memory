from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .types import ClientIdentity, ExecutionContext, MemorySpaceIdentity


class BridgeClientError(RuntimeError):
    def __init__(self, status: int | None, body: dict[str, Any] | None, message: str):
        super().__init__(message)
        self.status = status
        self.body = body


class BridgeClient:
    """Provider-neutral HTTP client used by desktop apps, agents and intermediaries.

    Browser extensions may implement the same Client Contract in JavaScript; they do not
    need this Python SDK. The SDK proves that client/product/model identity is provenance,
    while shared memory is keyed by memory_space.
    """

    def __init__(
        self,
        base_url: str,
        credential: str,
        client: ClientIdentity,
        memory_space: MemorySpaceIdentity,
        execution_context: ExecutionContext | None = None,
        *,
        timeout: float = 5.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.credential = credential
        self.client = client
        self.memory_space = memory_space
        self.execution_context = execution_context or ExecutionContext()
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.credential}"}
        if data is not None:
            headers.update({"Content-Type":"application/json","Content-Length":str(len(data))})
        req = Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = None
            raise BridgeClientError(exc.code, body, f"Bridge HTTP {exc.code}") from exc
        except URLError as exc:
            raise BridgeClientError(None, None, f"Bridge unavailable: {exc.reason}") from exc

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/v1/health")

    def capabilities(self) -> dict[str, Any]:
        return self._request("GET", "/v1/capabilities")

    def recall(self, user_text: str, *, session_id: str, turn_id: str | None = None, transaction_id: str | None = None, scopes: list[str] | None = None, max_items: int = 12) -> dict[str, Any]:
        tx = transaction_id or str(uuid.uuid4())
        turn = turn_id or tx
        payload = {
            "contract_version":"1.0",
            "transaction_id":tx,
            "client":asdict(self.client),
            "memory_space":asdict(self.memory_space),
            "execution_context":asdict(self.execution_context),
            "session_id":session_id,
            "turn_id":turn,
            "query":{"user_text":user_text,"scopes":scopes or ["user"],"max_items":max_items},
        }
        return self._request("POST", "/v1/recall", payload)

    def capture(self, user_text: str, assistant_text: str, *, session_id: str, turn_id: str | None = None, transaction_id: str | None = None, injected_memory_ids: list[str] | None = None, explicit_remember_request: bool = False, idempotency_key: str | None = None) -> dict[str, Any]:
        tx = transaction_id or str(uuid.uuid4())
        turn = turn_id or tx
        idem = idempotency_key or f"capture:{tx}"
        payload = {
            "contract_version":"1.0",
            "transaction_id":tx,
            "client":asdict(self.client),
            "memory_space":asdict(self.memory_space),
            "execution_context":asdict(self.execution_context),
            "session_id":session_id,
            "turn_id":turn,
            "idempotency_key":idem,
            "turn":{
                "user_text":user_text,
                "assistant_text":assistant_text,
                "injected_memory_ids":injected_memory_ids or [],
                "explicit_remember_request":explicit_remember_request,
            },
        }
        return self._request("POST", "/v1/capture", payload)

    def close_session(self, session_id: str, *, transaction_id: str | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        tx = transaction_id or str(uuid.uuid4())
        payload = {
            "contract_version":"1.0",
            "transaction_id":tx,
            "client":asdict(self.client),
            "session_id":session_id,
            "idempotency_key":idempotency_key or f"session-close:{session_id}",
        }
        return self._request("POST", "/v1/session/close", payload)
