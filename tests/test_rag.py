def test_rag_retrieves_reservation_modification_policy(rag):
    matches = rag.retrieve("modify reservation dates room availability", top_k=3)
    assert matches
    assert matches[0]["policy_id"] == "POL-RES-01"


def test_rag_retrieves_gold_policy(rag):
    matches = rag.retrieve("Gold late checkout", top_k=3)
    assert matches
    assert matches[0]["policy_id"] == "POL-LOY-01"


def test_policy_evidence_blocks_unsupported_airport_transportation(rag):
    evidence = rag.evaluate_evidence("Do Gold members get free airport transportation?")
    assert evidence["matches"]
    assert evidence["matches"][0]["policy_id"] == "POL-LOY-01"
    assert "airport" not in evidence["matches"][0]["text"].lower()
    assert evidence["matches"][0]["similarity_score"] < evidence["min_relevance_score"]
    assert evidence["evidence_status"] == "NOT_SUPPORTED"
    assert evidence["answer_allowed"] is False
    assert evidence["requires_escalation"] is True


def test_policy_evidence_supports_gold_late_checkout(rag):
    evidence = rag.evaluate_evidence("Do Gold members get late checkout?")
    assert evidence["matches"][0]["policy_id"] == "POL-LOY-01"
    assert evidence["evidence_status"] == "SUPPORTED"
    assert evidence["answer_allowed"] is True
    assert evidence["requires_escalation"] is False


def test_conflicting_policy_evidence_is_blocked(rag, monkeypatch):
    monkeypatch.setattr(
        rag,
        "retrieve",
        lambda query, top_k=3: [
            {
                "policy_id": "POL-A",
                "title": "Gold Breakfast Benefit",
                "text": "Gold members may receive complimentary breakfast.",
                "similarity_score": 0.92,
                "embedding_similarity_score": 0.8,
                "claim_coverage": 1.0,
            },
            {
                "policy_id": "POL-B",
                "title": "Gold Breakfast Restriction",
                "text": "Gold members must not receive complimentary breakfast.",
                "similarity_score": 0.90,
                "embedding_similarity_score": 0.79,
                "claim_coverage": 1.0,
            },
        ],
    )
    evidence = rag.evaluate_evidence("Do Gold members get complimentary breakfast?")
    assert evidence["evidence_status"] == "CONFLICTING"
    assert evidence["answer_allowed"] is False
    assert evidence["requires_escalation"] is True
