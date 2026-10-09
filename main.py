from __future__ import annotations

import logging

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from agent import HotelAgent
from config import settings
from database import Database, initialize_schema, seed_from_json
from rag import PolicyRAG
from schemas import (
    ApproveActionRequest,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    PolicySearchRequest,
    RejectActionRequest,
)
from tools import HotelTools


db = Database(settings.database_path)
initialize_schema(db)

# If the user's original hotel_demo.db is not present, the delivered project includes
# a fallback DB seeded from the user's own synthetic data. Existing non-empty DBs are preserved.
seed_file = settings.base_dir / "demo_seed.json"
if seed_file.exists():
    seed_from_json(db, seed_file)

rag = PolicyRAG(
    settings.policy_path,
    settings.rag_cache_path,
    embedding_model=settings.openai_embedding_model,
    api_key=settings.openai_api_key,
    offline=settings.offline_mode,
    threshold=settings.policy_candidate_threshold,
    min_relevance_score=settings.min_policy_relevance_score,
)
tools = HotelTools(db, rag)
agent = HotelAgent(
    tools,
    api_key=settings.openai_api_key,
    model=settings.openai_model,
    offline_mode=settings.offline_mode,
)

logger = logging.getLogger("coastalview")

app = FastAPI(title="CoastalView CRM + GenAI Demo", version="1.0.0")


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok" if db.ping() and rag.ready else "degraded",
        database="connected" if db.ping() else "error",
        rag="ready" if rag.ready else "error",
        mode="offline-test" if agent.offline_mode else "openai",
    )


@app.get("/api/customers")
def customers():
    return db.fetch_all("SELECT * FROM customers ORDER BY customer_id")


@app.get("/api/reservations")
def reservations():
    return db.fetch_all(
        """SELECT r.*, c.full_name AS customer_name
           FROM reservations r JOIN customers c ON c.customer_id = r.customer_id
           ORDER BY r.reservation_id"""
    )


@app.get("/api/cases")
def cases():
    return db.fetch_all("SELECT * FROM crm_cases ORDER BY case_id")


@app.get("/api/audit")
def audit():
    return db.fetch_all("SELECT * FROM audit_log ORDER BY id DESC LIMIT 100")


@app.post("/api/policies/search")
def policy_search(request: PolicySearchRequest):
    # Policy search exposes the same backend grounding decision used by the agent.
    assessment = rag.evaluate_evidence(request.query, top_k=3)
    return assessment


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if request.simulate_failure and not settings.enable_test_failure_mode:
        raise HTTPException(status_code=403, detail="Test failure mode is disabled.")
    try:
        result = agent.chat(request.message, request.session_id, request.simulate_failure)
        return ChatResponse(**result.__dict__)
    except Exception as exc:
        # Keep browser errors generic, but log the actual exception in the server
        # terminal so API/model/tool integration problems can be diagnosed.
        logger.exception("Chat workflow failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail="The assistant workflow failed. No operational write was performed. Please escalate or retry.",
        ) from exc


@app.post("/api/actions/approve")
def approve(request: ApproveActionRequest):
    if request.simulate_failure and not settings.enable_test_failure_mode:
        raise HTTPException(status_code=403, detail="Test failure mode is disabled.")
    try:
        return tools.approve_pending_action(
            request.action_id,
            selected_room_type=request.selected_room_type,
            simulate_failure=request.simulate_failure,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=500,
            detail="The approved write failed and was rolled back. The reservation remains unchanged.",
        ) from exc


@app.post("/api/actions/reject")
def reject(request: RejectActionRequest):
    try:
        return tools.reject_pending_action(request.action_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


frontend_dir = settings.base_dir / "frontend"
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
