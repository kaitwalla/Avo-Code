from pathlib import Path

from avo_harness.assistant import ChatStore, parse_decision


def test_execute_requires_concrete_evidence_and_acceptance() -> None:
    decision = parse_decision(
        '''{
          "reply": "I found the failing path and can implement it.",
          "action": "execute",
          "objective": "Fix expired-session refresh without changing the cookie format",
          "evidence": [
            {"fact": "refresh rejects expired sessions before renewal", "source": "src/auth/session.py:refresh_session"},
            {"fact": "the regression test expects one refresh attempt", "source": "tests/test_auth.py:test_expired_refresh"}
          ],
          "acceptance": ["expired sessions refresh once and valid sessions still load"],
          "constraints": ["keep the existing cookie format"],
          "question": ""
        }'''
    )
    assert decision.execution_ready is True
    assert decision.action == "execute"


def test_execute_is_downgraded_when_evidence_is_thin() -> None:
    decision = parse_decision(
        '''{
          "reply": "This is probably the fix.",
          "action": "execute",
          "objective": "Change the session refresh flow",
          "evidence": [{"fact": "there is session code", "source": "src/auth/session.py"}],
          "acceptance": ["tests pass"],
          "constraints": [],
          "question": ""
        }'''
    )
    assert decision.execution_ready is False
    assert decision.action == "clarify"
    assert decision.question


def test_non_json_worker_output_stays_conversational() -> None:
    decision = parse_decision("The router chooses the highest-quality eligible strategy first.")
    assert decision.action == "answer"
    assert decision.execution_ready is False
    assert "router" in decision.reply


def test_chat_store_persists_messages_and_metadata(tmp_path: Path) -> None:
    store = ChatStore(tmp_path / "state.sqlite3")
    user_id = store.add_message("main", "user", "Why is auth failing?")
    assistant_id = store.add_message("main", "assistant", "Checking…", kind="thinking", status="thinking")
    store.update_message(
        assistant_id,
        content="The state endpoint rejects the shared session.",
        kind="text",
        status="complete",
        metadata={"action": "answer"},
    )
    messages = store.messages("main")
    assert [item["id"] for item in messages] == [user_id, assistant_id]
    assert messages[1]["metadata"]["action"] == "answer"
    assert messages[1]["status"] == "complete"
