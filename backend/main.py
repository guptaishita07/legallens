"""
main.py — LegalLens FastAPI application (Phase 1)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.database import init_db
from routers import documents, qa


app = FastAPI(
    title="LegalLens API",
    description="Contract intelligence platform — RAG-powered legal document analysis",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(qa.router)


@app.on_event("startup")
def startup():
    """Initialise DB tables and pgvector extension on first run."""
    init_db()
    print("✓ LegalLens API ready")


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


# ── Run directly ──────────────────────────────────────────────────────────────
# uvicorn main:app --reload --port 8000
