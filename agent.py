from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from tools import HotelTools, TOOL_DEFINITIONS


SYSTEM_INSTRUCTIONS = """
You are the CoastalView Hotels reservation support assistant used by authorized staff
in a synthetic training environment.

You help staff retrieve customer, reservation, loyalty, availability, CRM, and hotel
policy information using the available tools.

Never fabricate customer information, reservation information, availability, loyalty
status, or hotel policy. Always use tools when the answer depends on database or policy
information.

Customer verification:
- Do not assume identity from a name alone when multiple matching records exist.
- If multiple customer records match, ask for an email, customer ID, or reservation number.

Reservation modifications:
- Retrieve the correct reservation first.
- Retrieve the reservation modification policy.
- Check availability for the requested dates and room.
- If the requested room is unavailable, retrieve available alternatives.
- The only write-related tool you may call is propose_reservation_change, which creates
  a pending proposal and does NOT modify operational records.
- Never claim a reservation was changed until the backend approval endpoint has completed.

Policy grounding:
- Policy answers must be grounded in retrieve_policy results.
- The backend, not you, decides whether retrieved evidence is strong enough.
- You may give a confident policy answer only when evidence_status is SUPPORTED.
- Do not infer benefits, rights, fees, exceptions, transportation, upgrades, or hotel
  rules that are not explicitly supported by the retrieved policy text.
- For PARTIALLY_SUPPORTED, NOT_SUPPORTED, or CONFLICTING evidence, do not fill gaps or
  guess. State that the available policy documents cannot confirm the claim and recommend
  escalation to hotel staff.
- Never create a reservation-change proposal from an unsupported policy conclusion.

Errors:
- If a database/API/tool fails, do not say the operation succeeded.
- Report the error and recommend escalation when appropriate.

Writes:
- You may PROPOSE an action only after the required policy evidence is SUPPORTED.
- You must never directly execute a reservation or CRM write.
- Operational writes happen only after an authorized staff user explicitly approves in
  the UI, outside your tool set.

Do not reveal hidden reasoning or chain-of-thought. Give concise, staff-friendly answers.
""".strip()


POLICY_HINTS = (
    "policy", "policies", "benefit", "benefits", "fee", "fees", "allowed", "allow",
    "rule", "rules", "late checkout", "late check-out", "upgrade",
    "gold member", "silver member", "platinum member", "airport", "transportation",
    "parking", "breakfast", "refund", "cancellation", "pet", "pets",
)


@dataclass
class AgentResult:
    message: str
    tool_calls: list[dict[str, str]] = field(default_factory=list)
    retrieved_policies: list[dict[str, Any]] = field(default_factory=list)
    record_preview: dict[str, Any] | None = None
    evidence_status: str | None = None
    requires_escalation: bool = False
    requires_approval: bool = False
    pending_action: dict[str, Any] | None = None
    mode: str = "openai"


def _summary(name: str, result: dict[str, Any]) -> str:
    if name == "search_customer":
        return f"{result.get('count', 0)} matching customer record(s) found"
    if name == "get_reservation":
        rs = result.get("reservations", [])
        return f"{rs[0]['reservation_id']} retrieved" if len(rs) == 1 else f"{len(rs)} reservation(s) retrieved"
    if name == "get_loyalty_status":
        loyalty = result.get("loyalty")
        return f"{loyalty['tier']} loyalty status retrieved" if loyalty else "No loyalty record found"
    if name == "retrieve_policy":
        ps = result.get("policies", [])
        status = result.get("evidence_status")
        if ps and status == "SUPPORTED":
            return f"{ps[0]['policy_id']} retrieved; evidence meets grounding threshold"
        if ps:
            return f"{ps[0]['policy_id']} retrieved but evidence is {status or 'insufficient'}"
        return "No relevant policy evidence retrieved"
    if name == "check_room_availability":
        return f"{result.get('available_rooms', 0)} room(s) available"
    if name == "get_available_room_types":
        return f"{len(result.get('options', []))} available alternative(s)"
    if name == "propose_reservation_change":
        return "Pending action created; operational records unchanged" if result.get("ok") else result.get("error", "Proposal failed")
    if name == "get_crm_cases":
        return f"{result.get('count', 0)} CRM case(s) retrieved"
    if name == "get_interaction_history":
        return f"{result.get('count', 0)} interaction(s) retrieved"
    return "Tool completed"


def _append_activity(
    activities: list[dict[str, str]], name: str, result: dict[str, Any], *, status: str | None = None
) -> None:
    if name == "retrieve_policy":
        evidence_status = result.get("evidence_status")
        tool_status = "success" if evidence_status == "SUPPORTED" else "warning"
        activities.append(
            {"name": name, "result_summary": _summary(name, result), "status": tool_status}
        )
        activities.append(
            {
                "name": "evidence_check",
                "result_summary": (
                    f"{evidence_status}: {result.get('evidence_reason', 'Evidence evaluated by backend.')}"
                ),
                "status": "success" if evidence_status == "SUPPORTED" else "warning",
            }
        )
        return

    activities.append(
        {
            "name": name,
            "result_summary": _summary(name, result),
            "status": status or ("blocked" if result.get("blocked") else "success"),
        }
    )


class HotelAgent:
    def __init__(
        self,
        tools: HotelTools,
        *,
        api_key: str | None,
        model: str,
        offline_mode: bool,
    ):
        self.tools = tools
        self.api_key = api_key
        self.model = model
        self.offline_mode = offline_mode or not bool(api_key)

    @staticmethod
    def _looks_like_policy_question(message: str) -> bool:
        lower = message.lower()
        return any(hint in lower for hint in POLICY_HINTS)

    @staticmethod
    def _looks_like_reservation_change(message: str) -> bool:
        """Detect operational reservation-change intent for policy preflight.

        Names and requested dates are record context, not policy claims. The backend
        evaluates a canonical reservation-modification claim instead of scoring the
        entire user sentence against the policy text.
        """
        lower = message.lower()
        change_term = any(term in lower for term in ("move", "change", "modify", "reschedule"))
        reservation_context = any(
            term in lower
            for term in ("reservation", "booking", "stay", "check-in", "check in", "dates")
        )
        return change_term and reservation_context

    @staticmethod
    def _reservation_change_evidence_supported(policy_result: dict[str, Any] | None) -> bool:
        if not policy_result or not policy_result.get("answer_allowed"):
            return False
        for policy in policy_result.get("policies", []):
            identity = f"{policy.get('policy_id', '')} {policy.get('title', '')}".lower()
            if "reservation" in identity and ("modif" in identity or "change" in identity):
                return True
        return False

    def _dispatch(self, name: str, args: dict[str, Any], session_id: str) -> dict[str, Any]:
        if name == "propose_reservation_change":
            return self.tools.propose_reservation_change(session_id=session_id, **args)
        function = getattr(self.tools, name, None)
        if function is None:
            return {"error": f"Unknown tool: {name}"}
        return function(**args)

    def _blocked_policy_result(
        self,
        policy_result: dict[str, Any],
        *,
        activities: list[dict[str, str]],
        preview: dict[str, Any] | None = None,
        mode: str,
    ) -> AgentResult:
        status = policy_result.get("evidence_status") or "NOT_SUPPORTED"
        policies = policy_result.get("policies", [])
        activities.append(
            {
                "name": "policy_guard",
                "result_summary": "Unsupported policy answer blocked by backend grounding gate",
                "status": "blocked",
            }
        )
        activities.append(
            {
                "name": "escalation",
                "result_summary": "Staff review required; no write or approval action created",
                "status": "escalation",
            }
        )
        return AgentResult(
            message=(
                "I could not find sufficient policy evidence to confirm this benefit or rule. "
                "I will not assume it applies. Please confirm with hotel staff or escalate this request."
            ),
            tool_calls=activities,
            retrieved_policies=policies,
            record_preview=preview,
            evidence_status=status,
            requires_escalation=True,
            requires_approval=False,
            pending_action=None,
            mode=mode,
        )

    def chat(self, message: str, session_id: str, simulate_failure: bool = False) -> AgentResult:
        if simulate_failure:
            return AgentResult(
                message=(
                    "A simulated database/tool failure occurred. No records were changed. "
                    "Escalate to a staff user or retry after the system issue is resolved."
                ),
                tool_calls=[
                    {
                        "name": "database_test_failure",
                        "result_summary": "Simulated failure; no write executed",
                        "status": "warning",
                    }
                ],
                requires_escalation=True,
                mode="offline-test" if self.offline_mode else "openai",
            )

        # Backend identity guard: duplicate names are blocked before any model call.
        # This makes customer verification reliable in both live and offline modes.
        ambiguous = self.tools.find_ambiguous_customer_mention(message)
        if ambiguous:
            name = ambiguous["name"]
            count = ambiguous["count"]
            count_text = "two" if count == 2 else str(count)
            return AgentResult(
                message=(
                    f"I found {count_text} customers named {name}. I will not guess which record "
                    "is correct. Please provide an email address, customer ID, or reservation "
                    "number before any reservation details are displayed or changed."
                ),
                tool_calls=[
                    {
                        "name": "customer_verification",
                        "result_summary": (
                            f"{count} matching CRM contacts found; ambiguous identity blocked"
                        ),
                        "status": "warning",
                    },
                    {
                        "name": "identity_guard",
                        "result_summary": (
                            "No reservation lookup or write allowed until a unique identifier is provided"
                        ),
                        "status": "blocked",
                    },
                ],
                record_preview={"customer_matches": ambiguous["customers"]},
                requires_escalation=False,
                requires_approval=False,
                pending_action=None,
                mode="offline-test" if self.offline_mode else "openai",
            )

        if self.offline_mode:
            return self._offline_chat(message, session_id)

        # Backend policy preflight:
        # - Policy questions are evaluated against the user's actual claim.
        # - Reservation changes use a canonical policy claim so customer names,
        #   dates, and record identifiers do not dilute the evidence score.
        preflight_policy: dict[str, Any] | None = None
        if self._looks_like_reservation_change(message):
            preflight_policy = self.tools.retrieve_policy(
                "modify reservation dates room availability staff approval"
            )
        elif self._looks_like_policy_question(message):
            preflight_policy = self.tools.retrieve_policy(message)

        if preflight_policy is not None and not preflight_policy.get("answer_allowed"):
            activities: list[dict[str, str]] = []
            _append_activity(activities, "retrieve_policy", preflight_policy)
            return self._blocked_policy_result(
                preflight_policy, activities=activities, mode="openai"
            )

        return self._openai_chat(message, session_id, preflight_policy=preflight_policy)

    def _openai_chat(
        self,
        message: str,
        session_id: str,
        *,
        preflight_policy: dict[str, Any] | None = None,
    ) -> AgentResult:
        # Current official OpenAI SDK + Responses API function/tool calling.
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        input_items: list[Any] = [{"role": "user", "content": message}]
        activities: list[dict[str, str]] = []
        policies: list[dict[str, Any]] = []
        preview: dict[str, Any] | None = None
        pending_action: dict[str, Any] | None = None
        evidence_status: str | None = None
        requires_escalation = False
        latest_policy_result: dict[str, Any] | None = None
        instructions = SYSTEM_INSTRUCTIONS

        if preflight_policy:
            _append_activity(activities, "retrieve_policy", preflight_policy)
            policies = list(preflight_policy.get("policies", []))
            evidence_status = preflight_policy.get("evidence_status")
            latest_policy_result = preflight_policy
            # The model gets only the backend-approved evidence, not a request to judge its sufficiency.
            approved_context = {
                "evidence_status": evidence_status,
                "policies": [
                    {
                        "policy_id": p["policy_id"],
                        "title": p["title"],
                        "text": p["text"],
                        "similarity_score": p["similarity_score"],
                    }
                    for p in policies
                ],
            }
            instructions += (
                "\n\nBackend grounding precheck: the following policy evidence is SUPPORTED. "
                "Use only these policy facts for the policy claim; do not add unstated benefits or exceptions.\n"
                + json.dumps(approved_context)
            )

        for _ in range(8):
            response = client.responses.create(
                model=self.model,
                instructions=instructions,
                tools=TOOL_DEFINITIONS,
                input=input_items,
            )

            # Include model output items (including reasoning/function calls) in the next turn.
            input_items.extend([item.model_dump(exclude_none=True) for item in response.output])
            calls = [item for item in response.output if getattr(item, "type", None) == "function_call"]

            if not calls:
                return AgentResult(
                    message=response.output_text or "No response generated.",
                    tool_calls=activities,
                    retrieved_policies=policies,
                    record_preview=preview,
                    evidence_status=evidence_status,
                    requires_escalation=requires_escalation,
                    requires_approval=bool(pending_action),
                    pending_action=pending_action,
                    mode="openai",
                )

            # Evaluate policy evidence first when the model emits parallel calls. A proposal
            # in the same turn is not allowed to race ahead of the grounding decision.
            calls = sorted(calls, key=lambda c: 0 if c.name == "retrieve_policy" else 1)

            for call in calls:
                try:
                    args = json.loads(call.arguments or "{}")

                    if call.name == "retrieve_policy" and preflight_policy is not None:
                        # Reuse the backend-approved one-shot evidence decision. This
                        # prevents a noisier model-generated query from weakening the
                        # already-validated grounding result.
                        result = preflight_policy
                    elif (
                        call.name == "propose_reservation_change"
                        and not self._reservation_change_evidence_supported(latest_policy_result)
                    ):
                        result = {
                            "ok": False,
                            "blocked": True,
                            "error": (
                                "Proposal blocked: SUPPORTED reservation-policy evidence is required "
                                "before a pending action may be created."
                            ),
                        }
                    else:
                        result = self._dispatch(call.name, args, session_id)
                except Exception as exc:
                    result = {"error": f"{type(exc).__name__}: {exc}"}

                _append_activity(activities, call.name, result)

                if call.name == "retrieve_policy":
                    policies = list(result.get("policies", []))
                    evidence_status = result.get("evidence_status")
                    latest_policy_result = result
                    requires_escalation = bool(result.get("requires_escalation"))

                    if not result.get("answer_allowed"):
                        return self._blocked_policy_result(
                            result,
                            activities=activities,
                            preview=preview,
                            mode="openai",
                        )
                elif call.name == "search_customer" and result.get("count") == 1:
                    preview = {"customer": result["customers"][0]}
                elif call.name == "get_reservation" and result.get("count") == 1:
                    preview = {**(preview or {}), "reservation": result["reservations"][0]}
                elif call.name == "get_loyalty_status" and result.get("loyalty"):
                    preview = {**(preview or {}), "loyalty": result["loyalty"]}
                elif call.name == "propose_reservation_change" and result.get("pending_action"):
                    pending_action = result["pending_action"]

                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(result),
                    }
                )

        return AgentResult(
            message="The agent reached its tool-call safety limit. No write was executed; please escalate.",
            tool_calls=activities,
            retrieved_policies=policies,
            record_preview=preview,
            evidence_status=evidence_status,
            requires_escalation=True,
            requires_approval=bool(pending_action),
            pending_action=pending_action,
            mode="openai",
        )

    def _offline_chat(self, message: str, session_id: str) -> AgentResult:
        """
        Deterministic developer/test mode for environments without OPENAI_API_KEY.
        It exercises the same database/RAG/approval tools but is NOT presented as LLM output.
        """
        lower = message.lower()
        activities: list[dict[str, str]] = []
        policies: list[dict[str, Any]] = []
        preview: dict[str, Any] = {}

        def call(tool_name: str, **kwargs: Any) -> dict[str, Any]:
            result = self._dispatch(tool_name, kwargs, session_id)
            _append_activity(activities, tool_name, result)
            return result

        # Ambiguous-customer demo
        if "john smith" in lower:
            found = call("search_customer", name="John Smith", email=None, customer_id=None)
            return AgentResult(
                message=(
                    "I found two customers named John Smith. I will not guess which record is correct. "
                    "Please provide an email address, customer ID, or reservation number before any "
                    "reservation details are displayed or changed."
                ),
                tool_calls=activities,
                record_preview={"customer_matches": found["customers"]},
                mode="offline-test",
            )

        # This fallback demo has a known synthetic Jessica record.
        if "jessica" in lower:
            found = call("search_customer", name="Jessica Turner", email=None, customer_id=None)
            if found["count"] != 1:
                return AgentResult(
                    message="Jessica Turner could not be uniquely verified. No action was taken.",
                    tool_calls=activities,
                    mode="offline-test",
                )
            customer = found["customers"][0]
            preview["customer"] = customer
            reservation_result = call(
                "get_reservation", reservation_id=None, customer_id=customer["customer_id"]
            )
            reservation = reservation_result["reservations"][0] if reservation_result["reservations"] else None
            if reservation:
                preview["reservation"] = reservation

            loyalty_result = call("get_loyalty_status", customer_id=customer["customer_id"])
            loyalty = loyalty_result.get("loyalty")
            if loyalty:
                preview["loyalty"] = loyalty

            # Policy/benefits scenario. The backend evidence status is authoritative.
            if self._looks_like_policy_question(message):
                policy_result = call("retrieve_policy", query=message)
                policies = policy_result.get("policies", [])
                if not policy_result.get("answer_allowed"):
                    return self._blocked_policy_result(
                        policy_result,
                        activities=activities,
                        preview=preview,
                        mode="offline-test",
                    )
                p = policies[0]
                msg = (
                    f"Jessica Turner is a {loyalty['tier']} member with {loyalty['points']:,} points. "
                    f"Based on {p['policy_id']} — {p['title']}: {p['text']}"
                )
                return AgentResult(
                    message=msg,
                    tool_calls=activities,
                    retrieved_policies=policies,
                    record_preview=preview,
                    evidence_status="SUPPORTED",
                    mode="offline-test",
                )

            # Modification scenario
            if any(term in lower for term in ["move", "change", "modify", "nov 10", "november 10"]):
                policy_result = call("retrieve_policy", query="modify reservation dates room availability")
                policies = policy_result.get("policies", [])
                if not policy_result.get("answer_allowed"):
                    return self._blocked_policy_result(
                        policy_result,
                        activities=activities,
                        preview=preview,
                        mode="offline-test",
                    )

                availability = call(
                    "check_room_availability",
                    hotel_name=reservation["hotel_name"],
                    check_in="2026-11-10",
                    check_out="2026-11-13",
                    room_type=reservation["room_type"],
                )
                proposal = call(
                    "propose_reservation_change",
                    reservation_id=reservation["reservation_id"],
                    check_in="2026-11-10",
                    check_out="2026-11-13",
                    room_type=reservation["room_type"],
                )
                action = proposal.get("pending_action")
                if not action:
                    return AgentResult(
                        message=proposal.get("error", "I could not prepare the reservation change."),
                        tool_calls=activities,
                        retrieved_policies=policies,
                        record_preview=preview,
                        evidence_status="SUPPORTED",
                        mode="offline-test",
                    )
                options = action.get("room_options", [])
                if availability["available"]:
                    msg = (
                        f"{reservation['room_type']} is available for Nov 10–13. "
                        "I prepared a pending change. The reservation is still unchanged until staff approves."
                    )
                else:
                    option_text = ", ".join(
                        f"{x['room_type']} ({x['available_rooms']} available)" for x in options
                    )
                    msg = (
                        f"The requested {reservation['room_type']} is unavailable for Nov 10–13. "
                        f"Available alternatives: {option_text}. Select an option and approve. "
                        "No reservation change has been written yet."
                    )
                return AgentResult(
                    message=msg,
                    tool_calls=activities,
                    retrieved_policies=policies,
                    record_preview=preview,
                    evidence_status="SUPPORTED",
                    requires_approval=True,
                    pending_action=action,
                    mode="offline-test",
                )

            # Normal read
            return AgentResult(
                message=(
                    f"Jessica Turner's reservation {reservation['reservation_id']} is at "
                    f"{reservation['hotel_name']} from {reservation['check_in']} to {reservation['check_out']} "
                    f"in a {reservation['room_type']}. Loyalty status: {loyalty['tier']} "
                    f"with {loyalty['points']:,} points."
                ),
                tool_calls=activities,
                record_preview=preview,
                mode="offline-test",
            )

        # General policy question without a customer lookup, e.g. the grounding-failure demo.
        if self._looks_like_policy_question(message):
            policy_result = call("retrieve_policy", query=message)
            policies = policy_result.get("policies", [])
            if not policy_result.get("answer_allowed"):
                return self._blocked_policy_result(
                    policy_result,
                    activities=activities,
                    mode="offline-test",
                )
            p = policies[0]
            return AgentResult(
                message=f"Based on {p['policy_id']} — {p['title']}: {p['text']}",
                tool_calls=activities,
                retrieved_policies=policies,
                evidence_status="SUPPORTED",
                mode="offline-test",
            )

        return AgentResult(
            message=(
                "Offline/test mode supports the required synthetic demo scenarios. "
                "Add OPENAI_API_KEY and set OFFLINE_MODE=false for open-ended LLM tool calling."
            ),
            mode="offline-test",
        )
