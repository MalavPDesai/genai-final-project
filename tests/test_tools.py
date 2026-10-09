import pytest


def _reservation(tools):
    return tools.get_reservation(reservation_id="RSV784562")["reservations"][0]


def test_unapproved_proposal_does_not_modify_reservation(tools):
    before = _reservation(tools).copy()
    proposal = tools.propose_reservation_change(
        session_id="test",
        reservation_id="RSV784562",
        check_in="2026-11-10",
        check_out="2026-11-13",
        room_type="Deluxe King",
    )
    after = _reservation(tools)
    assert proposal["requires_approval"] is True
    assert after == before


def test_approved_write_modifies_sqlite(tools):
    proposal = tools.propose_reservation_change(
        session_id="test",
        reservation_id="RSV784562",
        check_in="2026-11-10",
        check_out="2026-11-13",
        room_type="Deluxe King",
    )
    result = tools.approve_pending_action(
        proposal["pending_action"]["action_id"],
        selected_room_type="Deluxe Queen",
    )
    updated = _reservation(tools)
    assert updated["check_in"] == "2026-11-10"
    assert updated["check_out"] == "2026-11-13"
    assert updated["room_type"] == "Deluxe Queen"
    assert updated["status"] == "Modified"
    assert result["crm_case"]["status"] == "Closed"


def test_crm_case_updated_after_approval(tools):
    proposal = tools.propose_reservation_change(
        session_id="test",
        reservation_id="RSV784562",
        check_in="2026-11-10",
        check_out="2026-11-13",
        room_type="Deluxe King",
    )
    tools.approve_pending_action(
        proposal["pending_action"]["action_id"],
        selected_room_type="Executive King",
    )
    cases = tools.get_crm_cases("C1001")["cases"]
    assert cases[0]["status"] == "Closed"
    assert "RSV784562" in cases[0]["resolution"]


def test_failed_write_transaction_rolls_back(tools):
    before = _reservation(tools).copy()
    proposal = tools.propose_reservation_change(
        session_id="test",
        reservation_id="RSV784562",
        check_in="2026-11-10",
        check_out="2026-11-13",
        room_type="Deluxe King",
    )
    with pytest.raises(RuntimeError):
        tools.approve_pending_action(
            proposal["pending_action"]["action_id"],
            selected_room_type="Deluxe Queen",
            simulate_failure=True,
        )
    after = _reservation(tools)
    assert after == before
    action = tools.get_pending_action(proposal["pending_action"]["action_id"])
    assert action["status"] == "pending"
