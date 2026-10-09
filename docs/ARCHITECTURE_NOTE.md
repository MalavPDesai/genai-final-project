# CoastalView Architecture Note

## Purpose

CoastalView is a synthetic hotel-support prototype that integrates customer records,
reservations, loyalty data, room inventory, CRM cases, hotel-policy retrieval, and an
OpenAI-powered assistant behind a FastAPI backend.

## Data flow

```text
Staff User
   |
   v
Browser Frontend (HTML/CSS/JS)
   |
   | REST
   v
FastAPI Backend (main.py)
   |
   +--> HotelAgent (agent.py)
   |       |
   |       +--> OpenAI Responses API
   |       +--> predefined tool calls only
   |
   +--> HotelTools (tools.py)
   |       |
   |       +--> customer / reservation / loyalty reads
   |       +--> room availability
   |       +--> CRM reads
   |       +--> reservation-change proposal
   |
   +--> PolicyRAG (rag.py)
   |       |
   |       +--> embeddings + cosine retrieval
   |       +--> evidence classifier
   |       +--> SUPPORTED / PARTIALLY_SUPPORTED /
   |            NOT_SUPPORTED / CONFLICTING
   |
   +--> SQLite (hotel_demo.db)
           |
           +--> pending_actions
           +--> explicit approval endpoint
           +--> transactional reservation + CRM write
           +--> audit_log
```

## Main components

- `frontend/`: staff-facing browser UI.
- `main.py`: FastAPI routes, frontend hosting, approval/rejection endpoints.
- `agent.py`: OpenAI tool loop, system instructions, ambiguity and grounding preflight.
- `tools.py`: safe tool surface; the LLM cannot issue arbitrary SQL.
- `database.py`: SQLite access, schema, CRM adapter, and write transaction.
- `rag.py`: policy chunking, embeddings, retrieval, and evidence classification.
- `config.py`: environment-controlled model, database, and grounding settings.

## Write safety

The model cannot directly update a reservation. It can create a pending proposal.
Only an explicit staff approval call executes the reservation + CRM write. The write
runs in a transaction and records audit entries.

## Grounding safety

Policy answers are not trusted solely to the LLM. The backend enforces
`MIN_POLICY_RELEVANCE_SCORE` and checks direct claim support and conflicts. Weak or
unsupported evidence is blocked and escalated.

## Data boundary

All included data are synthetic. The OpenAI key is local in `.env`; `.env` is ignored
by Git and is not part of this repository.
