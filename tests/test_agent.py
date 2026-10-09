
from agent import AgentResult, HotelAgent


def test_offline_required_scenarios(tools):
    agent = HotelAgent(tools, api_key=None, model="test", offline_mode=True)

    read = agent.chat("Show me Jessica Turner's reservation and loyalty status.", "s1")
    assert "RSV784562" in read.message
    assert read.record_preview["loyalty"]["tier"] == "Gold"

    ambiguous = agent.chat("Change John Smith's reservation.", "s2")
    assert "two customers named John Smith" in ambiguous.message
    assert ambiguous.requires_approval is False

    policy = agent.chat("What benefits does Jessica get as a Gold member?", "s3")
    assert any(p["policy_id"] == "POL-LOY-01" for p in policy.retrieved_policies)

    failure = agent.chat("Simulate a tool failure.", "s4", simulate_failure=True)
    assert "No records were changed" in failure.message


def test_unsupported_policy_answer_is_blocked_without_database_write(tools):
    agent = HotelAgent(tools, api_key=None, model="test", offline_mode=True)
    before = {
        "reservations": tools.db.fetch_all("SELECT * FROM reservations ORDER BY reservation_id"),
        "crm_cases": tools.db.fetch_all("SELECT * FROM crm_cases ORDER BY case_id"),
        "pending_actions": tools.db.fetch_all("SELECT * FROM pending_actions ORDER BY action_id"),
        "audit_log": tools.db.fetch_all("SELECT * FROM audit_log ORDER BY id"),
    }

    result = agent.chat(
        "Do Gold members get free airport transportation?",
        "unsupported-policy",
    )

    after = {
        "reservations": tools.db.fetch_all("SELECT * FROM reservations ORDER BY reservation_id"),
        "crm_cases": tools.db.fetch_all("SELECT * FROM crm_cases ORDER BY case_id"),
        "pending_actions": tools.db.fetch_all("SELECT * FROM pending_actions ORDER BY action_id"),
        "audit_log": tools.db.fetch_all("SELECT * FROM audit_log ORDER BY id"),
    }

    assert result.evidence_status == "NOT_SUPPORTED"
    assert result.requires_escalation is True
    assert result.requires_approval is False
    assert result.pending_action is None
    assert any(p["policy_id"] == "POL-LOY-01" for p in result.retrieved_policies)
    assert "airport transportation" not in result.message.lower() or "confirm" in result.message.lower()
    assert "will not assume" in result.message.lower()
    assert before == after


def test_supported_gold_late_checkout_answer_is_grounded(tools):
    agent = HotelAgent(tools, api_key=None, model="test", offline_mode=True)

    result = agent.chat("Do Gold members get late checkout?", "supported-policy")

    assert result.evidence_status == "SUPPORTED"
    assert result.requires_escalation is False
    assert result.requires_approval is False
    assert any(p["policy_id"] == "POL-LOY-01" for p in result.retrieved_policies)
    assert "late checkout up to 2:00 pm" in result.message.lower()
    assert "when available" in result.message.lower()


def test_live_mode_ambiguous_customer_is_blocked_before_openai(tools, monkeypatch):
    """Duplicate identity must be handled by backend preflight, not by the model."""
    agent = HotelAgent(tools, api_key="test-key", model="test-model", offline_mode=False)

    def should_not_call_openai(*args, **kwargs):
        raise AssertionError("OpenAI should not be called for an ambiguous customer name")

    monkeypatch.setattr(agent, "_openai_chat", should_not_call_openai)

    result = agent.chat("Change John Smith's reservation.", "live-ambiguity-test")

    assert "two customers named John Smith" in result.message
    assert result.requires_approval is False
    assert result.pending_action is None
    assert result.record_preview is not None
    assert len(result.record_preview["customer_matches"]) == 2
    assert any(item["name"] == "identity_guard" for item in result.tool_calls)


def test_live_reservation_change_uses_supported_backend_policy_preflight(tools, monkeypatch):
    """Operational reservation requests must use supported reservation-policy evidence."""
    agent = HotelAgent(tools, api_key="test-key", model="test-model", offline_mode=False)
    captured = {}

    def fake_openai_chat(message, session_id, *, preflight_policy=None):
        captured["policy"] = preflight_policy
        return AgentResult(
            message="preflight ok",
            evidence_status=preflight_policy.get("evidence_status") if preflight_policy else None,
            mode="openai",
        )

    monkeypatch.setattr(agent, "_openai_chat", fake_openai_chat)

    result = agent.chat(
        "Move Jessica Turner's reservation to Nov 10–13.",
        "reservation-preflight",
    )

    assert result.message == "preflight ok"
    assert captured["policy"] is not None
    assert captured["policy"]["evidence_status"] == "SUPPORTED"
    assert captured["policy"]["answer_allowed"] is True
    assert captured["policy"]["policies"][0]["policy_id"] == "POL-RES-01"
