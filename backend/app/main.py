"""
TraceX API entrypoint.

Run in development (from backend/, venv active):
    uvicorn app.main:app --reload --port 8000

Interactive API docs at http://localhost:8000/docs
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, cases, copilot, entities, ml, reports, wallets
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import Base, engine
from app.ingestion.provider_registry import live_chains

configure_logging()
logger = get_logger(__name__)
settings = get_settings()

app = FastAPI(
    title="TraceX",
    description=(
        "Explainable cryptocurrency investigation platform for law-enforcement use. "
        "Traces victim-reported wallets, clusters related addresses, detects laundering "
        "patterns and generates evidence-backed VASP candidates."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(cases.router)
app.include_router(wallets.router)
app.include_router(entities.router)
app.include_router(reports.router)
app.include_router(ml.router)
app.include_router(copilot.router)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info(
        "tracex.started",
        environment=settings.environment,
        graph_backend=settings.graph_backend,
        workers=settings.workers_enabled,
        copilot=settings.copilot_enabled,
        live_chains=live_chains(),
    )


@app.get("/api/health")
def health():
    """Reports what is actually wired up, so an operator can see at a glance
    which capabilities are live versus needing configuration."""
    from app.risk.ml_inference import RiskModel

    return {
        "status": "ok",
        "environment": settings.environment,
        "chains_live": live_chains(),
        "etherscan_key_configured": bool(settings.etherscan_api_key),
        "graph_backend": settings.graph_backend,
        "workers_enabled": settings.workers_enabled,
        "copilot_enabled": settings.copilot_enabled,
        "risk_model_loaded": RiskModel.instance().available,
    }
