# Prompt + Iteration Log

This log summarizes the main AI-assisted development iterations used for the project.

## Iteration 1 — Convert the browser demo into a working integration

**Goal:** Preserve the existing CoastalView UI while replacing browser-only mock state
with a FastAPI backend, SQLite data access, safe tools, RAG, approval before writes,
CRM write-back, audit logging, and tests.

**Implemented:**
- FastAPI backend
- synthetic SQLite database seeded from `demo_seed.json`
- CRM adapter boundary
- OpenAI Responses API tool-calling path
- policy RAG
- pending reservation actions
- explicit approval/rejection endpoints
- transactional write-back and audit logging
- automated tests

## Iteration 2 — Add policy grounding / hallucination protection

**Goal:** Prevent confident hotel-policy answers when retrieved evidence is too weak.

**Implemented:**
- configurable `MIN_POLICY_RELEVANCE_SCORE`
- evidence states `SUPPORTED`, `PARTIALLY_SUPPORTED`, `NOT_SUPPORTED`, `CONFLICTING`
- backend-enforced answer blocking
- escalation flag
- supported Gold late-checkout test
- unsupported airport-transportation test
- conflicting-evidence test

## Iteration 3 — Improve Windows setup

**Goal:** Make the project easier for teammates to run.

**Implemented:**
- `START_COASTALVIEW.bat`
- virtual-environment creation
- dependency installation
- `.env` initialization
- browser launch

## Iteration 4 — Fix live ambiguous-customer handling

**Observed issue:** In live mode, `Change John Smith's reservation.` could enter the
model/tool loop before the duplicate-name edge case was resolved.

**Fix:** Duplicate-customer detection was moved into a deterministic backend preflight.
The system now blocks the ambiguous identity before an OpenAI call and asks for an
email, customer ID, or reservation number.

## Iteration 5 — Fix reservation-policy grounding for operational changes

**Observed issue:** The grounding gate scored the entire operational request, including
customer name and dates, which could dilute policy relevance and incorrectly block a
valid reservation change.

**Fix:** Reservation-change intent now uses a backend-owned canonical policy query:
`modify reservation dates room availability staff approval`. This preserves the
hallucination guard for policy questions while allowing a supported operational
reservation workflow.

## Current measured automated result

The final repository test suite passes **19/19 tests**.
