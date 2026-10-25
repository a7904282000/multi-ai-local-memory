from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BridgeError(Exception):
    code: str
    message: str
    boundary: str
    retryable: bool = False
    transaction_id: str | None = None
    http_status: int = 500

    def to_dict(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "boundary": self.boundary,
                "transaction_id": self.transaction_id,
            }
        }


class InvalidRequest(BridgeError):
    def __init__(self, message: str, transaction_id: str | None = None):
        super().__init__("INVALID_REQUEST", message, "REQUEST_VALIDATION", False, transaction_id, 400)


class UnsupportedVersion(BridgeError):
    def __init__(self, version: str | None, transaction_id: str | None = None):
        super().__init__("UNSUPPORTED_VERSION", f"Unsupported contract version: {version}", "CONTRACT_VERSION", False, transaction_id, 400)


class AuthFailed(BridgeError):
    def __init__(self, transaction_id: str | None = None):
        super().__init__("AUTH_FAILED", "Client authentication failed", "CLIENT_AUTH", False, transaction_id, 401)


class Forbidden(BridgeError):
    def __init__(self, message: str = "Client is not authorized for this operation", transaction_id: str | None = None):
        super().__init__("FORBIDDEN", message, "CLIENT_AUTHZ", False, transaction_id, 403)


class IdempotencyConflict(BridgeError):
    def __init__(self, transaction_id: str | None = None):
        super().__init__("IDEMPOTENCY_CONFLICT", "Idempotency key was reused with a different payload", "IDEMPOTENCY", False, transaction_id, 409)


class StorageUnavailable(BridgeError):
    def __init__(self, message: str = "Storage is unavailable", transaction_id: str | None = None):
        super().__init__("STORAGE_UNAVAILABLE", message, "STORAGE", True, transaction_id, 503)
