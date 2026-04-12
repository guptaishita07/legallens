"""
main.py — LegalLens FastAPI application (Phase 3)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db.database import init_db
from routers import documents, qa, auth, comparison, reports

app = FastAPI(
    title="LegalLens API",
    description="Contract intelligence platform — RAG, clause extraction, risk scoring, comparison",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(qa.router)
app.include_router(comparison.router)
app.include_router(reports.router)


@app.on_event("startup")
def startup():
    init_db()
    print("✓ LegalLens API v0.3.0 ready")


@app.get("/health")
def health():
    return {"status": "ok", "version": "0.3.0"}
