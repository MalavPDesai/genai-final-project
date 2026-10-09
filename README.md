# CoastalView CRM + GenAI Prototype

A graduate-school demo showing a synthetic hotel support workflow with:

- FastAPI backend
- SQLite customer/reservation/CRM data
- OpenAI Responses API function/tool calling
- policy RAG using embeddings + cosine similarity
- backend-enforced policy evidence/grounding gate
- explicit human approval before reservation writes
- transactional reservation + CRM update
- backend audit log
- a browser UI served by FastAPI

> **Synthetic academic demo only.** The included records are fake examples supplied with the original frontend.

## Easiest Windows start — double-click

For the presentation/demo, you can use the included:

`START_COASTALVIEW.bat`

You do **not** need to activate a virtual environment or type Uvicorn commands manually.

1. Extract the project ZIP.
2. Double-click `START_COASTALVIEW.bat`.
3. If Python is missing, the launcher attempts to install Python 3.12 using Windows `winget`.
4. On first launch, it creates `.venv` and installs the requirements automatically.
5. If your OpenAI key has not been configured yet, `.env` opens in Notepad. Paste the key after `OPENAI_API_KEY=`, save, and close Notepad.
6. The launcher starts FastAPI and opens `http://127.0.0.1:8000` automatically.
7. Keep the launcher window open while using the site. Press `Ctrl+C` in that window to stop the server.

Your API key stays in the backend `.env` file and is never placed in the browser-side JavaScript.

If automatic Python installation is unavailable, install Python 3.12 once from python.org, then double-click the launcher again.

---

## Important note about the supplied files

The uploaded bundle contained the frontend files and `data.json`, but did **not** contain the original `hotel_demo.db` or `hotel_policies.txt`.

To make the delivered project runnable, this project includes:

- `hotel_demo.db` generated from the supplied synthetic `demo_seed.json`
- `hotel_policies.txt` generated from the supplied synthetic policy entries

If you later recover your original database/policy file, make a backup and replace these files only after confirming the schema/content matches what the code expects.

The original uploaded frontend is backed up in:

`original_frontend_backup/`

---

## 1. Install Python

Install Python 3.11 or newer from python.org.

On Windows, make sure **Add Python to PATH** is checked.

Verify:

```powershell
python --version
```

## 2. Create a virtual environment

Open PowerShell in the `coastalview_ai` folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
```

## 3. Install requirements

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 4. Create `.env`

Copy the example:

```powershell
Copy-Item .env.example .env
```

Open `.env` and set:

```env
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-6-luna
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
POLICY_CANDIDATE_THRESHOLD=0.08
MIN_POLICY_RELEVANCE_SCORE=0.72
OFFLINE_MODE=false
ENABLE_TEST_FAILURE_MODE=true
```

Never put the API key in `frontend/app.js` or `index.html`.

`.env` is ignored by Git.

### No API key yet?

Leave `OPENAI_API_KEY=` blank and set:

```env
OFFLINE_MODE=true
```

The required presentation scenarios still run in deterministic developer/test mode. This mode uses the same SQLite, RAG interface, pending actions, approvals, transactions, and audit log, but it is clearly labeled as **offline-test** and is not pretending to be live LLM output.

---

## 5. Run the app

From the project folder:

```powershell
uvicorn main:app --reload
```

Open:

`http://127.0.0.1:8000`

Health endpoint:

`http://127.0.0.1:8000/api/health`

Expected shape:

```json
{
  "status": "ok",
  "database": "connected",
  "rag": "ready",
  "mode": "openai"
}
```

If no API key is configured, `mode` will be `offline-test`.

---

## 6. Run the demo scenarios

### Scenario A — normal read

Use:

`Show me Jessica Turner's reservation and loyalty status.`

You should see customer, reservation, and loyalty read tools in Agent Activity.

### Scenario B — modification + approval

Use:

`Move Jessica Turner's reservation to Nov 10-13.`

Expected:

1. Jessica is uniquely found.
2. Reservation `RSV784562` is retrieved.
3. Modification policy is retrieved.
4. Deluxe King has zero availability.
5. Deluxe Queen and Executive King are offered.
6. Nothing operational changes yet.
7. Click **Approve Deluxe Queen**.
8. Reservation and CRM case update in one SQLite transaction.
9. Reservations, Cases, and Audit Log refresh.

### Scenario C — ambiguous customer

Use:

`Change John Smith's reservation.`

Two John Smith contacts are returned. The agent must request another identifier and must not guess.

### Scenario D — policy RAG

Use:

`What benefits does Jessica get as a Gold member?`

The system retrieves Jessica's loyalty record and the Gold policy section.

Also open **Policies / RAG** and search:

`Gold late checkout`


### Scenario D2 — unsupported policy claim / grounding guard

Click **Unsupported policy question**, which sends:

`Do Gold members get free airport transportation?`

Expected:

1. RAG still retrieves the related Gold loyalty policy as a candidate.
2. The backend calculates the evidence score and compares it with `MIN_POLICY_RELEVANCE_SCORE` (default `0.72`).
3. Because the policy never states an airport-transportation benefit, the evidence is `NOT_SUPPORTED`.
4. The backend blocks a confident policy answer before it can be presented.
5. The response shows **Insufficient Retrieved Evidence** and requires staff escalation.
6. `requires_approval` is false and no pending action, reservation, CRM, or audit write is created.

For a positive comparison, ask:

`Do Gold members get late checkout?`

That should be `SUPPORTED` and return the policy-defined late checkout up to 2:00 PM when available.

### Scenario E — safe system failure

Click **System error test**.

The UI should report failure and must not claim a write succeeded.

Transaction rollback is also covered by automated tests.

---

## 7. Run automated tests

```powershell
pytest -q
```

Expected final result for this repository:

```text
19 passed
```

The tests use a temporary copy/test database, not the delivered demo database.

They verify the original database/approval scenarios plus the grounding guard, including:

- Jessica/reservation/Gold lookups and duplicate John Smith handling;
- room availability and reservation-policy retrieval;
- pending action safety, approval write-back, CRM update, and transaction rollback;
- unsupported Gold airport-transportation evidence is `NOT_SUPPORTED`;
- the unsupported question creates no database write or approval action;
- Gold late checkout is `SUPPORTED` and returns the policy-defined 2:00 PM / availability condition.

---

## Project structure

```text
coastalview_ai/
    main.py              FastAPI routes + frontend hosting
    agent.py             OpenAI Responses API tool loop + offline test mode
    tools.py             Safe LLM tools + approval/write functions
    database.py          SQLite helper + CRM adapter + transactions
    rag.py               Policy retrieval + evidence classification/grounding gate
    schemas.py           Pydantic API models
    config.py            Environment settings

    hotel_demo.db         Synthetic SQLite demo DB
    hotel_policies.txt   Synthetic policy source
    demo_seed.json        Source used to construct fallback demo DB

    frontend/
        index.html
        styles.css
        app.js

    original_frontend_backup/
        ...

    tests/
        conftest.py
        test_database.py
        test_tools.py
        test_rag.py
        test_agent.py

    docs/
        ARCHITECTURE_NOTE.md
        PROMPT_ITERATION_LOG.md

    requirements.txt
    .env.example
    .gitignore
    README.md
```

---

## How RAG + the evidence gate work

`rag.py` deliberately separates **retrieval** from **permission to answer**.

1. `hotel_policies.txt` is split on headings such as:

   `## POL-LOY-01 | Gold Loyalty Benefits`

2. Each policy section is embedded and cached in `.rag_embeddings.json`.
3. The user's policy query is embedded and candidates are retrieved.
4. A calibrated relevance score combines semantic similarity with direct claim-term coverage.
5. The backend evidence classifier checks the configured `MIN_POLICY_RELEVANCE_SCORE`, direct claim support, ambiguous near-ties, and conflicting policy evidence.
6. It returns one of `SUPPORTED`, `PARTIALLY_SUPPORTED`, `NOT_SUPPORTED`, or `CONFLICTING`.
7. Only `SUPPORTED` evidence sets `answer_allowed=true`.
8. Any other status is blocked and escalated; the LLM is not allowed to decide that weak evidence is "good enough."

The low `POLICY_CANDIDATE_THRESHOLD` is intentionally permissive so a related document can still be shown in a failure case. The stronger `MIN_POLICY_RELEVANCE_SCORE` is the actual grounding safety gate.

With `OFFLINE_MODE=false`, the code uses the OpenAI embeddings endpoint. With `OFFLINE_MODE=true`, tests use deterministic local vectors so the suite does not need network/API access.

---

## How tool calling works

The browser never talks to OpenAI directly.

Flow:

```text
Browser
  -> POST /api/chat
FastAPI
  -> HotelAgent
OpenAI Responses API
  -> requests safe tool
FastAPI executes tool
  -> returns function_call_output
OpenAI
  -> final staff-facing response
```

The LLM can call only the explicit tools defined in `tools.py`.

It cannot submit arbitrary SQL.

Operational write functions are **not** exposed as ordinary model tools.

---

## How approval/write-back works

The model can call:

`propose_reservation_change(...)`

That creates a row in `pending_actions`.

It does **not** change the reservation.

The browser then shows approval buttons.

Only a user click sends:

`POST /api/actions/approve`

The backend starts one SQLite transaction that:

1. re-checks availability,
2. updates the reservation,
3. updates or creates the CRM case,
4. records audit rows,
5. marks the pending action approved,
6. commits.

Any exception causes a rollback.

Rejecting calls:

`POST /api/actions/reject`

and changes only the pending-action status.

---

## CRM adapter / future SuiteCRM

`database.py` defines a small `CRMAdapter` interface and the current:

`SQLiteCRMAdapter`

For this academic version, SQLite is the CRM data source.

A later `SuiteCRMAdapter` can implement the same methods with authenticated SuiteCRM REST requests.

No SuiteCRM credentials are invented or required.

---

## What is real versus simulated?

### Fully functional in this prototype

- FastAPI serving one website
- SQLite reads
- SQLite reservation write-back
- CRM case update/create
- transaction rollback
- pending approval actions
- rejection
- backend audit log
- frontend API integration
- policy chunking
- embedding cache
- cosine-similarity retrieval
- OpenAI Responses API code path
- OpenAI embeddings code path

### Still intentionally not production-integrated

- live SuiteCRM is not required; `SQLiteCRMAdapter` is the current CRM source;
- staff authentication/RBAC is not implemented in this academic prototype;
- no real customer data is included;
- live OpenAI mode requires each user to create a local `.env` file containing an authorized `OPENAI_API_KEY`; API keys are never committed to the repository.

### Development fallback

When no `OPENAI_API_KEY` is available:

- the required chat scenarios run through deterministic `offline-test` routing;
- the test RAG uses local deterministic vectors.

This fallback is intentionally labeled and is not represented as real LLM output.

---

## Useful API endpoints

```text
GET  /api/health
GET  /api/customers
GET  /api/reservations
GET  /api/cases
GET  /api/audit

POST /api/chat
POST /api/policies/search
POST /api/actions/approve
POST /api/actions/reject
```

---

## Suggested assignment screenshots

Capture these in order:

1. **AI Assistant — normal read**  
   Show Jessica's SQLite reservation + Gold status and Agent Activity.

2. **Modification before approval**  
   Show Deluxe King unavailable and alternate room approval buttons.

3. **After approval**  
   Show the updated `RSV784562` row on Reservations.

4. **CRM Cases after approval**  
   Show `CASE9001` closed with the written resolution.

5. **Audit Log / Side Effects**  
   Show the real backend write records.

6. **Ambiguous John Smith**  
   Show two matching customer records and the refusal to guess.

7. **Policies / RAG — supported**  
   Search `Gold late checkout` and show `POL-LOY-01`, relevance score, `SUPPORTED`, and answer allowed.

8. **Grounding failure**  
   Click **Unsupported policy question** and capture `NOT_SUPPORTED`, **Insufficient Retrieved Evidence**, blocked answer, and escalation. Then search the same question on **Policies / RAG** to show the below-threshold score.

9. **System error test**  
   Show the failure message that explicitly says no successful write is being claimed.

10. **Architecture page**  
   Use this as the final implementation diagram.

11. **Terminal running `pytest -q`**  
    Capture the passing test summary as implementation evidence.
