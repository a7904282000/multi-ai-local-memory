from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .errors import AuthFailed, Forbidden
from .types import ClientIdentity


@dataclass(frozen=True, slots=True)
class Principal:
    client_id: str
    scopes: frozenset[str] = field(default_factory=frozenset)
    memory_spaces: frozenset[str] = field(default_factory=lambda: frozenset({"*"}))
    admin: bool = False

    def can_access_space(self, space_id: str) -> bool:
        return "*" in self.memory_spaces or space_id in self.memory_spaces


class AuthProvider(Protocol):
    def authenticate(self, credential: str | None, claimed: ClientIdentity | None) -> Principal:
        ...


class StaticTokenAuth:
    """Test/dev auth adapter. Production provisioning is intentionally outside the core contract."""

    def __init__(self, tokens: dict[str, Principal]):
        self._tokens = dict(tokens)

    def authenticate(self, credential: str | None, claimed: ClientIdentity | None) -> Principal:
        if not credential or credential not in self._tokens:
            raise AuthFailed()
        principal = self._tokens[credential]
        if claimed and claimed.client_id != principal.client_id:
            raise Forbidden("Authenticated client_id does not match claimed client_id")
        return principal


class SQLiteCredentialRegistry:
    """Persistent per-client credential registry for production-style local deployments.

    Tokens are generated with high entropy and only their SHA-256 hashes are stored.
    Provisioning is a local/trusted control-plane action; it is intentionally not exposed
    as a public web route by the Bridge application API.
    """

    def __init__(self, db_path):
        import sqlite3
        from pathlib import Path
        self._sqlite3 = sqlite3
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        c = self._sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = self._sqlite3.Row
        return c

    def _init_db(self):
        c = self._connect()
        try:
            c.execute("""
                CREATE TABLE IF NOT EXISTS credentials (
                    credential_id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL UNIQUE,
                    client_id TEXT NOT NULL,
                    client_type TEXT NOT NULL,
                    client_instance_id TEXT NOT NULL,
                    scopes_json TEXT NOT NULL,
                    memory_spaces_json TEXT NOT NULL,
                    admin INTEGER NOT NULL DEFAULT 0,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_credentials_client ON credentials(client_id, client_instance_id)")
            c.commit()
        finally:
            c.close()

    @staticmethod
    def _hash(token: str) -> str:
        import hashlib
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def provision(self, claimed: ClientIdentity, *, scopes=(), memory_spaces=("*",), admin: bool = False) -> dict:
        import json, secrets, uuid
        from .types import utc_now
        token = "malm1_" + secrets.token_urlsafe(32)
        credential_id = "cred_" + uuid.uuid4().hex
        c = self._connect()
        try:
            c.execute(
                "INSERT INTO credentials VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    credential_id, self._hash(token), claimed.client_id, claimed.client_type,
                    claimed.client_instance_id, json.dumps(sorted(set(scopes))),
                    json.dumps(sorted(set(memory_spaces))), int(bool(admin)), 0, utc_now(),
                ),
            )
            c.commit()
        finally:
            c.close()
        return {"credential_id": credential_id, "token": token}

    def revoke(self, credential_id: str) -> None:
        c = self._connect()
        try:
            c.execute("UPDATE credentials SET revoked=1 WHERE credential_id=?", (credential_id,))
            c.commit()
        finally:
            c.close()

    def revoke_client_instance(self, claimed: ClientIdentity) -> int:
        c = self._connect()
        try:
            cur = c.execute(
                "UPDATE credentials SET revoked=1 WHERE client_id=? AND client_type=? AND client_instance_id=? AND revoked=0",
                (claimed.client_id, claimed.client_type, claimed.client_instance_id),
            )
            c.commit()
            return int(cur.rowcount or 0)
        finally:
            c.close()

    def rotate_for_client(self, claimed: ClientIdentity, *, scopes=(), memory_spaces=("*",), admin: bool = False) -> dict:
        self.revoke_client_instance(claimed)
        return self.provision(claimed, scopes=scopes, memory_spaces=memory_spaces, admin=admin)

    def authenticate(self, credential: str | None, claimed: ClientIdentity | None) -> Principal:
        import json
        if not credential:
            raise AuthFailed()
        c = self._connect()
        try:
            row = c.execute(
                "SELECT * FROM credentials WHERE token_hash=? AND revoked=0",
                (self._hash(credential),),
            ).fetchone()
        finally:
            c.close()
        if row is None:
            raise AuthFailed()
        if claimed is not None:
            if claimed.client_id != row["client_id"]:
                raise Forbidden("Authenticated client_id does not match claimed client_id")
            if claimed.client_type != row["client_type"]:
                raise Forbidden("Authenticated client_type does not match provisioned client_type")
            if claimed.client_instance_id != row["client_instance_id"]:
                raise Forbidden("Authenticated client_instance_id does not match provisioned client instance")
        return Principal(
            client_id=row["client_id"],
            scopes=frozenset(json.loads(row["scopes_json"])),
            memory_spaces=frozenset(json.loads(row["memory_spaces_json"])),
            admin=bool(row["admin"]),
        )

    def health(self) -> dict:
        c = self._connect()
        try:
            active = c.execute("SELECT COUNT(*) FROM credentials WHERE revoked=0").fetchone()[0]
        finally:
            c.close()
        return {"status":"PASS","auth":"sqlite-credential-registry","active_credentials":active,"db_path":str(self.db_path)}
