# CoastalView CRM + GenAI Demo

This is a self-contained static website prototype for presenting the Part A concept.

## What it demonstrates
- CRM contact retrieval
- reservation retrieval
- loyalty lookup
- RAG-style policy retrieval
- room availability check
- ambiguous customer edge case
- human approval before a write
- reservation write-back (simulated in browser state)
- CRM case update
- audit log
- baseline vs GenAI metrics
- proposed architecture

## How to run
Because the site loads data.json, serve this folder through a tiny local web server instead of double-clicking index.html.

### Option A: Python
Open a terminal in this folder and run:

python -m http.server 8000

Then open:
http://localhost:8000

### Option B: VS Code
Use the Live Server extension and open index.html.

## Important implementation note
This is a functional front-end prototype. The "write-back" works inside browser state for demonstration.
For the graded implementation, replace the JavaScript demo functions with real backend endpoints or Python tool calls connected to:
- SQLite (included in the earlier asset package), and/or
- SuiteCRM API
- an LLM tool-calling layer

Suggested backend endpoints:
GET /api/customer?name=
GET /api/reservation/{id}
GET /api/loyalty/{customer_id}
GET /api/policy?q=
POST /api/reservation/{id}/modify
POST /api/crm/case/{id}/resolve

## Presentation flow
1. Show the manual fragmentation problem.
2. Open AI Assistant.
3. Run Jessica Turner request.
4. Point out the tool-call timeline.
5. Show that Deluxe King is unavailable.
6. Approve an alternate room.
7. Open Reservations and Cases to prove the records changed.
8. Run the John Smith edge case.
9. Open Policies / RAG and search "Gold late checkout".
10. Show Before vs After metrics.
11. End on Architecture and explain what you will replace with real APIs/tool calling.
