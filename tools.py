from __future__ import annotations

import json
import uuid
from typing import Any

from database import Database, SQLiteCRMAdapter, utc_now
from rag import PolicyRAG


class HotelTools:
    """Safe tool surface. No arbitrary SQL and no model-triggered operational writes."""

    def __init__(self, db: Database, rag: PolicyRAG):
        self.db = db
        self.crm = SQLiteCRMAdapter(db)
        self.rag = rag

    # Database read
    def search_customer(
        self, name: str | None = None, email: str | None = None, customer_id: str | None = None
    ) -> dict[str, Any]:
        rows = self.crm.search_customer(name=name, email=email, customer_id=customer_id)
        return {"count": len(rows), "customers": rows}

    def find_ambiguous_customer_mention(self, message: str) -> dict[str, Any] | None:
        """Read-only identity preflight.

        Duplicate customer names are detected before any LLM call so the application
        never depends on the model to notice an ambiguous identity.
        """
        duplicate_names = self.db.fetch_all(
            """SELECT full_name, COUNT(*) AS match_count
               FROM customers
               GROUP BY full_name
               HAVING COUNT(*) > 1
               ORDER BY full_name"""
        )
        lower_message = message.casefold()
        for row in duplicate_names:
            full_name = row["full_name"]
            if full_name.casefold() in lower_message:
                matches = self.crm.search_customer(name=full_name)
                return {
                    "ambiguous": True,
                    "name": full_name,
                    "count": len(matches),
                    "customers": matches,
                }
        return None

    def get_reservation(
        self, reservation_id: str | None = None, customer_id: str | None = None
    ) -> dict[str, Any]:
        if not reservation_id and not customer_id:
            return {"count": 0, "reservations": [], "error": "reservation_id or customer_id is required"}
        if reservation_id:
            rows = self.db.fetch_all(
                "SELECT * FROM reservations WHERE reservation_id = ?", (reservation_id,)
            )
        else:
            rows = self.db.fetch_all(
                "SELECT * FROM reservations WHERE customer_id = ? ORDER BY check_in", (customer_id,)
            )
        return {"count": len(rows), "reservations": rows}

    def get_loyalty_status(self, customer_id: str) -> dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM loyalty WHERE customer_id = ?", (customer_id,))
        return {"found": bool(row), "loyalty": row}

    def check_room_availability(
        self, hotel_name: str, check_in: str, check_out: str, room_type: str
    ) -> dict[str, Any]:
        from datetime import date

        nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
        if nights <= 0:
            return {
                "hotel_name": hotel_name, "check_in": check_in, "check_out": check_out,
                "room_type": room_type, "available_rooms": 0, "available": False,
                "nights_checked": 0, "error": "check_out must be after check_in",
            }

        row = self.db.fetch_one(
            """SELECT COUNT(*) AS nights_found, MIN(available_rooms) AS min_available
               FROM room_inventory
               WHERE hotel_name = ? AND stay_date >= ? AND stay_date < ? AND room_type = ?""",
            (hotel_name, check_in, check_out, room_type),
        )
        nights_found = int(row["nights_found"]) if row else 0
        available = int(row["min_available"]) if row and row["min_available"] is not None else 0
        full_coverage = nights_found == nights
        return {
            "hotel_name": hotel_name,
            "check_in": check_in,
            "check_out": check_out,
            "room_type": room_type,
            "available_rooms": available if full_coverage else 0,
            "available": full_coverage and available > 0,
            "nights_checked": nights_found,
            "required_nights": nights,
        }

    def get_available_room_types(self, hotel_name: str, check_in: str, check_out: str) -> dict[str, Any]:
        from datetime import date

        nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
        if nights <= 0:
            return {"options": []}
        rows = self.db.fetch_all(
            """SELECT room_type, MIN(available_rooms) AS available_rooms, COUNT(*) AS nights_found
               FROM room_inventory
               WHERE hotel_name = ? AND stay_date >= ? AND stay_date < ? AND available_rooms > 0
               GROUP BY room_type
               HAVING COUNT(*) = ?
               ORDER BY available_rooms DESC, room_type""",
            (hotel_name, check_in, check_out, nights),
        )
        for row in rows:
            row.pop("nights_found", None)
        return {"options": rows}

    def get_crm_cases(self, customer_id: str) -> dict[str, Any]:
        rows = self.crm.get_cases(customer_id)
        return {"count": len(rows), "cases": rows}

    def get_interaction_history(self, customer_id: str) -> dict[str, Any]:
        rows = self.db.fetch_all(
            "SELECT * FROM interactions WHERE customer_id = ? ORDER BY timestamp DESC", (customer_id,)
        )
        return {"count": len(rows), "interactions": rows}

    # RAG retrieval + deterministic evidence/grounding check.
    # The LLM receives this decision; it does not decide whether weak evidence is enough.
    def retrieve_policy(self, query: str) -> dict[str, Any]:
        assessment = self.rag.evaluate_evidence(query, top_k=3)
        return {
            "count": len(assessment["matches"]),
            "policies": assessment["matches"],
            "evidence_status": assessment["evidence_status"],
            "evidence_reason": assessment["evidence_reason"],
            "min_relevance_score": assessment["min_relevance_score"],
            "answer_allowed": assessment["answer_allowed"],
            "requires_escalation": assessment["requires_escalation"],
        }

    def propose_reservation_change(
        self,
        session_id: str,
        reservation_id: str,
        check_in: str,
        check_out: str,
        room_type: str | None = None,
    ) -> dict[str, Any]:
        """
        Human approval gate (stage 1): create a pending proposal only.
        This never modifies reservations or CRM cases.
        """
        reservation = self.db.fetch_one(
            "SELECT * FROM reservations WHERE reservation_id = ?", (reservation_id,)
        )
        if not reservation:
            return {"ok": False, "error": "Reservation not found"}

        requested_room = room_type or reservation["room_type"]
        availability = self.check_room_availability(
            reservation["hotel_name"], check_in, check_out, requested_room
        )

        options: list[dict[str, Any]] = []
        changes: dict[str, Any] = {"check_in": check_in, "check_out": check_out, "room_type": requested_room}

        if not availability["available"]:
            options = self.get_available_room_types(
                reservation["hotel_name"], check_in, check_out
            )["options"]
            if not options:
                return {
                    "ok": False,
                    "requires_approval": False,
                    "error": "Requested room is unavailable and no alternatives were found.",
                    "availability": availability,
                }
            # Staff must choose one of these options before approval.
            changes["room_type"] = None

        action_id = str(uuid.uuid4())
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO pending_actions(
                    action_id, session_id, action, reservation_id, customer_id,
                    changes_json, room_options_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    action_id, session_id, "modify_reservation", reservation_id,
                    reservation["customer_id"], json.dumps(changes), json.dumps(options), utc_now()
                ),
            )

        return {
            "ok": True,
            "requires_approval": True,
            "pending_action": {
                "action_id": action_id,
                "action": "modify_reservation",
                "reservation_id": reservation_id,
                "changes": changes,
                "room_options": options,
                "status": "pending",
            },
            "availability": availability,
        }

    def get_pending_action(self, action_id: str) -> dict[str, Any] | None:
        row = self.db.fetch_one("SELECT * FROM pending_actions WHERE action_id = ?", (action_id,))
        if not row:
            return None
        return {
            "action_id": row["action_id"],
            "session_id": row["session_id"],
            "action": row["action"],
            "reservation_id": row["reservation_id"],
            "customer_id": row["customer_id"],
            "changes": json.loads(row["changes_json"]),
            "room_options": json.loads(row["room_options_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "resolved_at": row["resolved_at"],
        }

    # Database write-back: only called from /api/actions/approve.
    def approve_pending_action(
        self, action_id: str, selected_room_type: str | None = None, simulate_failure: bool = False
    ) -> dict[str, Any]:
        pending = self.get_pending_action(action_id)
        if not pending:
            raise ValueError("Pending action not found.")
        if pending["status"] != "pending":
            raise ValueError(f"Action is already {pending['status']}.")

        changes = dict(pending["changes"])
        options = pending["room_options"]
        if changes.get("room_type") is None:
            valid_rooms = {item["room_type"] for item in options}
            if selected_room_type not in valid_rooms:
                raise ValueError("Select one of the available room alternatives before approval.")
            changes["room_type"] = selected_room_type

        with self.db.transaction() as conn:
            reservation = conn.execute(
                "SELECT * FROM reservations WHERE reservation_id = ?", (pending["reservation_id"],)
            ).fetchone()
            if not reservation:
                raise ValueError("Reservation no longer exists.")

            before = dict(reservation)

            # Re-check availability at approval time.
            from datetime import date

            required_nights = (
                date.fromisoformat(changes["check_out"]) - date.fromisoformat(changes["check_in"])
            ).days
            inv = conn.execute(
                """SELECT COUNT(*) AS nights_found, MIN(available_rooms) AS min_available
                   FROM room_inventory
                   WHERE hotel_name = ? AND stay_date >= ? AND stay_date < ? AND room_type = ?""",
                (
                    reservation["hotel_name"], changes["check_in"], changes["check_out"],
                    changes["room_type"]
                ),
            ).fetchone()
            if (
                not inv
                or required_nights <= 0
                or inv["nights_found"] != required_nights
                or inv["min_available"] is None
                or inv["min_available"] <= 0
            ):
                raise ValueError("Selected room is no longer available for every requested night. No changes were made.")

            conn.execute(
                """UPDATE reservations
                   SET check_in = ?, check_out = ?, room_type = ?, status = 'Modified'
                   WHERE reservation_id = ?""",
                (changes["check_in"], changes["check_out"], changes["room_type"], pending["reservation_id"]),
            )

            # Safe test hook: raise inside transaction to prove rollback.
            if simulate_failure:
                raise RuntimeError("Simulated write failure after reservation update.")

            updated = conn.execute(
                "SELECT * FROM reservations WHERE reservation_id = ?", (pending["reservation_id"],)
            ).fetchone()
            customer = conn.execute(
                "SELECT * FROM customers WHERE customer_id = ?", (pending["customer_id"],)
            ).fetchone()

            case = conn.execute(
                """SELECT * FROM crm_cases
                   WHERE customer_id = ? AND case_type = 'Reservation Modification Request'
                   ORDER BY case_id LIMIT 1""",
                (pending["customer_id"],),
            ).fetchone()

            resolution = (
                f"Reservation {pending['reservation_id']} moved to "
                f"{changes['check_in']} through {changes['check_out']}, "
                f"{changes['room_type']}, after explicit staff approval."
            )

            if case:
                case_id = case["case_id"]
                conn.execute(
                    "UPDATE crm_cases SET status = 'Closed', resolution = ? WHERE case_id = ?",
                    (resolution, case_id),
                )
            else:
                next_num = conn.execute(
                    "SELECT COALESCE(MAX(CAST(SUBSTR(case_id, 5) AS INTEGER)), 9000) + 1 FROM crm_cases"
                ).fetchone()[0]
                case_id = f"CASE{next_num}"
                conn.execute(
                    """INSERT INTO crm_cases(
                        case_id, customer_id, customer_name, case_type, description, status, resolution
                    ) VALUES (?, ?, ?, 'Reservation Modification Request', ?, 'Closed', ?)""",
                    (
                        case_id, pending["customer_id"], customer["full_name"],
                        "Created by approved GenAI reservation change.", resolution
                    ),
                )

            updated_case = conn.execute(
                "SELECT * FROM crm_cases WHERE case_id = ?", (case_id,)
            ).fetchone()

            conn.execute(
                """INSERT INTO audit_log(
                    timestamp, action, record_type, record_id, before_value, after_value, success
                ) VALUES (?, 'update_reservation', 'reservation', ?, ?, ?, 1)""",
                (utc_now(), pending["reservation_id"], json.dumps(before), json.dumps(dict(updated))),
            )
            conn.execute(
                """INSERT INTO audit_log(
                    timestamp, action, record_type, record_id, before_value, after_value, success
                ) VALUES (?, 'update_crm_case', 'crm_case', ?, ?, ?, 1)""",
                (
                    utc_now(), case_id, json.dumps(dict(case)) if case else None,
                    json.dumps(dict(updated_case))
                ),
            )
            conn.execute(
                "UPDATE pending_actions SET status = 'approved', resolved_at = ? WHERE action_id = ?",
                (utc_now(), action_id),
            )

            return {
                "message": "Write-back complete after explicit approval.",
                "reservation": dict(updated),
                "crm_case": dict(updated_case),
            }

    def reject_pending_action(self, action_id: str) -> dict[str, Any]:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT status FROM pending_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            if not row:
                raise ValueError("Pending action not found.")
            if row["status"] != "pending":
                raise ValueError(f"Action is already {row['status']}.")
            conn.execute(
                "UPDATE pending_actions SET status = 'rejected', resolved_at = ? WHERE action_id = ?",
                (utc_now(), action_id),
            )
        return {"message": "Pending action rejected. No reservation or CRM changes were made."}


TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "search_customer",
        "description": "Find synthetic CRM customers by exact name, email, or customer ID. Use this before revealing reservation details.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": ["string", "null"]},
                "email": {"type": ["string", "null"]},
                "customer_id": {"type": ["string", "null"]},
            },
            "required": ["name", "email", "customer_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_reservation",
        "description": "Get reservation records by reservation ID or verified customer ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "reservation_id": {"type": ["string", "null"]},
                "customer_id": {"type": ["string", "null"]},
            },
            "required": ["reservation_id", "customer_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_loyalty_status",
        "description": "Get a verified customer's loyalty tier and points.",
        "parameters": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}},
            "required": ["customer_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "check_room_availability",
        "description": "Check availability for a hotel, date range, and room type.",
        "parameters": {
            "type": "object",
            "properties": {
                "hotel_name": {"type": "string"},
                "check_in": {"type": "string"},
                "check_out": {"type": "string"},
                "room_type": {"type": "string"},
            },
            "required": ["hotel_name", "check_in", "check_out", "room_type"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_available_room_types",
        "description": "List available room alternatives for a hotel and date range.",
        "parameters": {
            "type": "object",
            "properties": {
                "hotel_name": {"type": "string"},
                "check_in": {"type": "string"},
                "check_out": {"type": "string"},
            },
            "required": ["hotel_name", "check_in", "check_out"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_crm_cases",
        "description": "Read CRM cases for a verified customer.",
        "parameters": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}},
            "required": ["customer_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "get_interaction_history",
        "description": "Read interaction history for a verified customer.",
        "parameters": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}},
            "required": ["customer_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "retrieve_policy",
        "description": "Retrieve 1-3 relevant hotel policy sections and a backend-enforced evidence status. Policy answers and policy-dependent proposals are allowed only when evidence_status is SUPPORTED.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "propose_reservation_change",
        "description": "Create a pending reservation-change proposal only. This does NOT modify the reservation. Use only after verifying the customer/reservation and checking policy/availability. If the requested room is unavailable, it creates a staff-selectable list of alternatives.",
        "parameters": {
            "type": "object",
            "properties": {
                "reservation_id": {"type": "string"},
                "check_in": {"type": "string"},
                "check_out": {"type": "string"},
                "room_type": {"type": ["string", "null"]},
            },
            "required": ["reservation_id", "check_in", "check_out", "room_type"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]
