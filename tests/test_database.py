def test_jessica_turner_can_be_found(tools):
    result = tools.search_customer(name="Jessica Turner")
    assert result["count"] == 1
    assert result["customers"][0]["customer_id"] == "C1001"


def test_rsv784562_can_be_retrieved(tools):
    result = tools.get_reservation(reservation_id="RSV784562")
    assert result["count"] == 1
    assert result["reservations"][0]["customer_id"] == "C1001"


def test_jessica_is_gold(tools):
    result = tools.get_loyalty_status("C1001")
    assert result["loyalty"]["tier"] == "Gold"


def test_two_john_smith_records_returned(tools):
    result = tools.search_customer(name="John Smith")
    assert result["count"] == 2


def test_deluxe_king_unavailable_for_requested_dates(tools):
    result = tools.check_room_availability(
        "CoastalView Seattle", "2026-11-10", "2026-11-13", "Deluxe King"
    )
    assert result["available"] is False
    assert result["available_rooms"] == 0
