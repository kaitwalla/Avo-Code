from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


@dataclass(slots=True)
class SessionInfo:
    token: str
    expires_at: str


class AuthStore:
    """Small auth store backed by the same SQLite file as Avo state.

    Connections are intentionally short-lived. FastAPI executes synchronous route
    handlers in a thread pool, so retaining one sqlite3 connection on the app object
    would violate SQLite's default same-thread contract under real request traffic.
    """

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10.0)
        db.row_factory = sqlite3.Row
        return db

    def close(self) -> None:
        # Kept for the same lifecycle shape as Store; connections are per operation.
        return None

    def _init_schema(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS auth_credentials (
                    credential_id TEXT PRIMARY KEY,
                    public_key BLOB NOT NULL,
                    sign_count INTEGER NOT NULL,
                    transports_json TEXT NOT NULL,
                    device_type TEXT NOT NULL,
                    backed_up INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS auth_challenges (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    challenge BLOB NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS auth_bootstrap (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    code_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS auth_meta (
                    key TEXT PRIMARY KEY,
                    value BLOB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_auth_challenges_expires
                  ON auth_challenges(expires_at);
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires
                  ON auth_sessions(expires_at);
                """
            )

    def credential_count(self) -> int:
        with self._connect() as db:
            row = db.execute("SELECT COUNT(*) AS n FROM auth_credentials").fetchone()
            return int(row["n"] if row else 0)

    def list_credentials(self) -> list[sqlite3.Row]:
        with self._connect() as db:
            return list(db.execute("SELECT * FROM auth_credentials ORDER BY created_at").fetchall())

    def credential(self, credential_id: str) -> sqlite3.Row | None:
        with self._connect() as db:
            return db.execute(
                "SELECT * FROM auth_credentials WHERE credential_id=?", (credential_id,)
            ).fetchone()

    def owner_handle(self) -> bytes:
        with self._connect() as db:
            row = db.execute("SELECT value FROM auth_meta WHERE key='owner_handle'").fetchone()
            if row is not None:
                return bytes(row["value"])
            value = secrets.token_bytes(32)
            db.execute("INSERT INTO auth_meta(key, value) VALUES('owner_handle', ?)", (value,))
            return value

    def issue_bootstrap_code(self, ttl_minutes: int = 10) -> tuple[str, str]:
        with self._connect() as db:
            row = db.execute("SELECT COUNT(*) AS n FROM auth_credentials").fetchone()
            if row and int(row["n"] or 0) > 0:
                raise RuntimeError("a passkey already exists; add additional passkeys while signed in")
            raw = secrets.token_hex(8).upper()
            code = "-".join(raw[index:index + 4] for index in range(0, len(raw), 4))
            expires = _now() + timedelta(minutes=ttl_minutes)
            db.execute(
                """INSERT INTO auth_bootstrap(id, code_hash, expires_at, used_at)
                   VALUES(1, ?, ?, NULL)
                   ON CONFLICT(id) DO UPDATE SET
                     code_hash=excluded.code_hash,
                     expires_at=excluded.expires_at,
                     used_at=NULL""",
                (_hash(code), _iso(expires)),
            )
            return code, _iso(expires)

    def validate_bootstrap(self, code: str) -> bool:
        with self._connect() as db:
            credential_row = db.execute("SELECT COUNT(*) AS n FROM auth_credentials").fetchone()
            if credential_row and int(credential_row["n"] or 0) > 0:
                return False
            row = db.execute("SELECT * FROM auth_bootstrap WHERE id=1").fetchone()
            if row is None or row["used_at"] is not None:
                return False
            if _parse(str(row["expires_at"])) <= _now():
                return False
            return hmac.compare_digest(str(row["code_hash"]), _hash(code.strip().upper()))

    def consume_bootstrap(self) -> None:
        with self._connect() as db:
            db.execute("UPDATE auth_bootstrap SET used_at=? WHERE id=1", (_iso(_now()),))

    def create_challenge(self, kind: str, challenge: bytes, ttl_minutes: int = 5) -> str:
        challenge_id = uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                "INSERT INTO auth_challenges(id, kind, challenge, expires_at, used_at) VALUES(?, ?, ?, ?, NULL)",
                (challenge_id, kind, challenge, _iso(_now() + timedelta(minutes=ttl_minutes))),
            )
        return challenge_id

    def consume_challenge(self, challenge_id: str, kind: str) -> bytes:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM auth_challenges WHERE id=? AND kind=?",
                (challenge_id, kind),
            ).fetchone()
            if row is None or row["used_at"] is not None:
                raise ValueError("authentication challenge is invalid or already used")
            if _parse(str(row["expires_at"])) <= _now():
                raise ValueError("authentication challenge expired")
            db.execute(
                "UPDATE auth_challenges SET used_at=? WHERE id=?",
                (_iso(_now()), challenge_id),
            )
            return bytes(row["challenge"])

    def add_credential(
        self,
        *,
        credential_id: str,
        public_key: bytes,
        sign_count: int,
        transports: list[str],
        device_type: str,
        backed_up: bool,
        label: str = "Passkey",
    ) -> None:
        with self._connect() as db:
            db.execute(
                """INSERT INTO auth_credentials
                   (credential_id, public_key, sign_count, transports_json, device_type,
                    backed_up, label, created_at, last_used_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                (
                    credential_id,
                    public_key,
                    sign_count,
                    json.dumps(transports),
                    device_type,
                    int(backed_up),
                    label,
                    _iso(_now()),
                ),
            )

    def update_credential_use(
        self, credential_id: str, *, sign_count: int, device_type: str, backed_up: bool
    ) -> None:
        with self._connect() as db:
            db.execute(
                """UPDATE auth_credentials SET sign_count=?, device_type=?, backed_up=?, last_used_at=?
                   WHERE credential_id=?""",
                (sign_count, device_type, int(backed_up), _iso(_now()), credential_id),
            )

    def issue_session(self, ttl_days: int = 30) -> SessionInfo:
        raw = secrets.token_urlsafe(48)
        now = _now()
        expires = now + timedelta(days=ttl_days)
        with self._connect() as db:
            db.execute(
                "INSERT INTO auth_sessions(token_hash, created_at, expires_at, last_seen_at) VALUES(?, ?, ?, ?)",
                (_hash(raw), _iso(now), _iso(expires), _iso(now)),
            )
        return SessionInfo(token=raw, expires_at=_iso(expires))

    def validate_session(self, token: str | None, ttl_days: int = 30) -> bool:
        if not token:
            return False
        digest = _hash(token)
        with self._connect() as db:
            row = db.execute("SELECT * FROM auth_sessions WHERE token_hash=?", (digest,)).fetchone()
            if row is None:
                return False
            now = _now()
            if _parse(str(row["expires_at"])) <= now:
                db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (digest,))
                return False
            db.execute(
                "UPDATE auth_sessions SET last_seen_at=?, expires_at=? WHERE token_hash=?",
                (_iso(now), _iso(now + timedelta(days=ttl_days)), digest),
            )
            return True

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        with self._connect() as db:
            db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (_hash(token),))


class PasskeyAuth:
    def __init__(self, store: AuthStore, *, rp_id: str, origin: str, rp_name: str = "Avo"):
        self.store = store
        self.rp_id = rp_id
        self.origin = origin.rstrip("/")
        self.rp_name = rp_name

    def registration_options(self) -> dict[str, Any]:
        try:
            from webauthn import base64url_to_bytes, generate_registration_options, options_to_json
            from webauthn.helpers.structs import (
                AuthenticatorSelectionCriteria,
                PublicKeyCredentialDescriptor,
                ResidentKeyRequirement,
                UserVerificationRequirement,
            )
        except ImportError as exc:  # pragma: no cover - deployment guard
            raise RuntimeError("passkey support requires avo-harness[web]") from exc

        challenge = secrets.token_bytes(32)
        challenge_id = self.store.create_challenge("registration", challenge)
        exclude = [
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(str(row["credential_id"])))
            for row in self.store.list_credentials()
        ]
        options = generate_registration_options(
            rp_id=self.rp_id,
            rp_name=self.rp_name,
            user_id=self.store.owner_handle(),
            user_name="owner",
            user_display_name="Avo Owner",
            challenge=challenge,
            exclude_credentials=exclude,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            timeout=120000,
        )
        return {"challenge_id": challenge_id, "options": json.loads(options_to_json(options))}

    def verify_registration(self, challenge_id: str, credential: dict[str, Any]) -> str:
        try:
            from webauthn import bytes_to_base64url, verify_registration_response
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("passkey support requires avo-harness[web]") from exc

        challenge = self.store.consume_challenge(challenge_id, "registration")
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=self.rp_id,
            expected_origin=self.origin,
            require_user_verification=True,
        )
        credential_id = bytes_to_base64url(verified.credential_id)
        response = credential.get("response") if isinstance(credential, dict) else None
        transports = []
        if isinstance(response, dict) and isinstance(response.get("transports"), list):
            transports = [str(item) for item in response["transports"]]
        self.store.add_credential(
            credential_id=credential_id,
            public_key=bytes(verified.credential_public_key),
            sign_count=int(verified.sign_count),
            transports=transports,
            device_type=_enum_value(verified.credential_device_type),
            backed_up=bool(verified.credential_backed_up),
        )
        return credential_id

    def authentication_options(self) -> dict[str, Any]:
        try:
            from webauthn import base64url_to_bytes, generate_authentication_options, options_to_json
            from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("passkey support requires avo-harness[web]") from exc

        rows = self.store.list_credentials()
        if not rows:
            raise ValueError("no passkeys are registered")
        challenge = secrets.token_bytes(32)
        challenge_id = self.store.create_challenge("authentication", challenge)
        allow = [
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(str(row["credential_id"])))
            for row in rows
        ]
        options = generate_authentication_options(
            rp_id=self.rp_id,
            challenge=challenge,
            allow_credentials=allow,
            user_verification=UserVerificationRequirement.REQUIRED,
            timeout=120000,
        )
        return {"challenge_id": challenge_id, "options": json.loads(options_to_json(options))}

    def verify_authentication(self, challenge_id: str, credential: dict[str, Any]) -> str:
        try:
            from webauthn import verify_authentication_response
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("passkey support requires avo-harness[web]") from exc

        credential_id = str(credential.get("id") or "")
        row = self.store.credential(credential_id)
        if row is None:
            raise ValueError("unknown passkey")
        challenge = self.store.consume_challenge(challenge_id, "authentication")
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=self.rp_id,
            expected_origin=self.origin,
            credential_public_key=bytes(row["public_key"]),
            credential_current_sign_count=int(row["sign_count"]),
            require_user_verification=True,
        )
        self.store.update_credential_use(
            credential_id,
            sign_count=int(verified.new_sign_count),
            device_type=_enum_value(verified.credential_device_type),
            backed_up=bool(verified.credential_backed_up),
        )
        return credential_id
