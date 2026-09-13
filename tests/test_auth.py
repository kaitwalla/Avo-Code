from pathlib import Path

import pytest

from avo_harness.api import _rp_id
from avo_harness.auth import AuthStore, PasskeyAuth


def test_bootstrap_code_is_one_time_and_disabled_after_first_passkey(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "state.sqlite3")
    try:
        code, expires_at = store.issue_bootstrap_code(ttl_minutes=10)
        assert expires_at
        assert store.validate_bootstrap(code)
        assert not store.validate_bootstrap("NOPE-0000")

        store.add_credential(
            credential_id="AQID",
            public_key=b"fake-key",
            sign_count=0,
            transports=["internal"],
            device_type="multi_device",
            backed_up=True,
        )
        assert not store.validate_bootstrap(code)
        with pytest.raises(RuntimeError, match="passkey already exists"):
            store.issue_bootstrap_code()
    finally:
        store.close()


def test_bootstrap_code_can_be_consumed(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "state.sqlite3")
    try:
        code, _ = store.issue_bootstrap_code()
        assert store.validate_bootstrap(code)
        store.consume_bootstrap()
        assert not store.validate_bootstrap(code)
    finally:
        store.close()


def test_session_issue_validate_and_revoke(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "state.sqlite3")
    try:
        session = store.issue_session(ttl_days=30)
        assert session.token
        assert store.validate_session(session.token)
        assert not store.validate_session("wrong-token")
        store.revoke_session(session.token)
        assert not store.validate_session(session.token)
    finally:
        store.close()


def test_registration_options_require_discoverable_verified_passkey(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "state.sqlite3")
    try:
        auth = PasskeyAuth(
            store,
            rp_id="avo.example.com",
            origin="https://avo.example.com",
        )
        result = auth.registration_options()
        assert result["challenge_id"]
        options = result["options"]
        assert options["rp"]["id"] == "avo.example.com"
        assert options["user"]["name"] == "owner"
        assert options["authenticatorSelection"]["residentKey"] == "required"
        assert options["authenticatorSelection"]["userVerification"] == "required"
    finally:
        store.close()


def test_authentication_options_allow_registered_credentials(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "state.sqlite3")
    try:
        store.add_credential(
            credential_id="AQID",
            public_key=b"fake-key",
            sign_count=0,
            transports=["internal"],
            device_type="multi_device",
            backed_up=True,
        )
        auth = PasskeyAuth(
            store,
            rp_id="avo.example.com",
            origin="https://avo.example.com",
        )
        result = auth.authentication_options()
        assert result["challenge_id"]
        options = result["options"]
        assert options["rpId"] == "avo.example.com"
        assert options["userVerification"] == "required"
        assert [item["id"] for item in options["allowCredentials"]] == ["AQID"]
    finally:
        store.close()


def test_rp_id_defaults_to_public_origin_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AVO_RP_ID", raising=False)
    assert _rp_id("https://avo.penginlab.com") == "avo.penginlab.com"
    monkeypatch.setenv("AVO_RP_ID", "penginlab.com")
    assert _rp_id("https://avo.penginlab.com") == "penginlab.com"
