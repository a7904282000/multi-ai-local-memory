from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .auth import Principal, StaticTokenAuth
from .core import BridgeCore
from .errors import BridgeError, Forbidden, InvalidRequest
from .storage.memory import InMemoryStorage


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "MALMBridge/0.1"

    def _json(self, status: int, body: dict):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _credential(self) -> str | None:
        auth = self.headers.get("Authorization", "")
        return auth[7:] if auth.startswith("Bearer ") else None

    def _payload(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(n) if n else b"{}"
            payload = json.loads(raw)
        except Exception as exc:
            raise InvalidRequest(f"Invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise InvalidRequest("Request body must be an object")
        return payload

    @property
    def core(self) -> BridgeCore:
        return self.server.core  # type: ignore[attr-defined]

    def do_GET(self):
        try:
            path = urlparse(self.path).path
            if path == "/v1/health":
                return self._json(200, self.core.health())
            if path == "/v1/capabilities":
                return self._json(200, self.core.capabilities())
            if path == "/v1/diagnostics":
                return self._json(200, self.core.diagnostics(self._credential()))
            return self._json(404, {"error": {"code": "NOT_FOUND", "message": "route not found", "retryable": False, "boundary": "HTTP_ROUTER", "transaction_id": None}})
        except BridgeError as exc:
            return self._json(exc.http_status, exc.to_dict())

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            payload = self._payload()
            credential = self._credential()
            if path == "/bootstrap/v1/browser":
                bootstrap = getattr(self.server, "browser_bootstrap", None)
                if bootstrap is None:
                    raise Forbidden("Browser bootstrap is not enabled")
                return self._json(200, bootstrap.provision(
                    payload,
                    origin=self.headers.get("Origin"),
                    remote_host=self.client_address[0] if self.client_address else None,
                ))
            if path == "/v1/recall":
                return self._json(200, self.core.recall(payload, credential))
            if path == "/v1/capture":
                return self._json(200, self.core.capture(payload, credential))
            if path == "/v1/session/close":
                return self._json(200, self.core.session_close(payload, credential))
            return self._json(404, {"error": {"code": "NOT_FOUND", "message": "route not found", "retryable": False, "boundary": "HTTP_ROUTER", "transaction_id": payload.get("transaction_id")}})
        except BridgeError as exc:
            return self._json(exc.http_status, exc.to_dict())

    def log_message(self, fmt, *args):
        return


def build_dev_core(token: str) -> BridgeCore:
    storage = InMemoryStorage()
    auth = StaticTokenAuth({
        token: Principal(client_id="dev-client", scopes=frozenset({"user", "project"}), memory_spaces=frozenset({"space-personal"}), admin=True)
    })
    return BridgeCore(storage, auth)


def main():
    p = argparse.ArgumentParser(description="Multi-AI Local Bridge reference core")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=18790)
    p.add_argument("--dev-token", default=os.getenv("MALM_DEV_TOKEN"))
    args = p.parse_args()
    if not args.dev_token:
        raise SystemExit("A development token is required for the reference server. Production provisioning is a separate adapter.")
    server = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
    server.core = build_dev_core(args.dev_token)  # type: ignore[attr-defined]
    server.serve_forever()


if __name__ == "__main__":
    main()
