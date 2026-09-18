from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_investigator
from app.core.config import get_settings
from app.db.models import Case, Investigator, WalletInvestigation
from app.db.session import SessionLocal, get_db
from app.ingestion.provider_registry import live_chains, supported_chains
from app.orchestrator.case_orchestrator import run_investigation_sync
from app.schemas.wallet import WalletInvestigateRequest, WalletInvestigationOut

router = APIRouter(prefix="/api/wallets", tags=["wallets"])
settings = get_settings()


def _run_in_background(investigation_id: str) -> None:
    """Runs the pipeline on its own DB session so the HTTP request can return
    immediately. When REDIS_URL is configured this same call is dispatched to
    a Celery worker instead (see app/workers/)."""
    db = SessionLocal()
    try:
        investigation = db.query(WalletInvestigation).filter_by(id=investigation_id).first()
        if investigation:
            run_investigation_sync(db, investigation)
    finally:
        db.close()


@router.get("/chains")
def chains():
    return {
        "supported": supported_chains(),
        "live": live_chains(),
        "note": "Chains listed under 'supported' but not 'live' are registered in the provider "
                "registry without an implemented adapter yet.",
    }


@router.post("/{case_id}/investigate", response_model=WalletInvestigationOut, status_code=status.HTTP_202_ACCEPTED)
def investigate(
    case_id: str,
    payload: WalletInvestigateRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    case = db.query(Case).filter_by(id=case_id).first()
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")
    if case.lead_investigator_id != investigator.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This case belongs to another investigator.")

    if payload.chain in ("ethereum", "polygon") and not settings.etherscan_api_key:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Set ETHERSCAN_API_KEY in backend/.env to trace Ethereum or Polygon addresses. "
            "Get a free key at https://etherscan.io/apidashboard",
        )

    investigation = WalletInvestigation(
        case_id=case.id,
        address=payload.address.lower(),
        chain=payload.chain,
        seed_tx_hash=payload.seed_tx_hash,
        max_hops=payload.max_hops,
        status="queued",
    )
    db.add(investigation)
    db.commit()
    db.refresh(investigation)

    if settings.workers_enabled:
        from app.workers.tasks import run_investigation_task  # local import: Celery is optional

        run_investigation_task.delay(investigation.id)
    else:
        background.add_task(_run_in_background, investigation.id)

    return investigation


@router.get("/investigations/{investigation_id}", response_model=WalletInvestigationOut)
def get_investigation(
    investigation_id: str,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    investigation = db.query(WalletInvestigation).filter_by(id=investigation_id).first()
    if not investigation:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Investigation not found.")
    case = db.query(Case).filter_by(id=investigation.case_id).first()
    if case.lead_investigator_id != investigator.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This investigation belongs to another investigator.")
    return investigation


@router.get("/investigations/{investigation_id}/graph")
def get_graph(
    investigation_id: str,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    investigation = get_investigation(investigation_id, db, investigator)
    graph = (investigation.summary or {}).get("graph")
    if not graph:
        raise HTTPException(status.HTTP_409_CONFLICT, "This investigation has not produced a graph yet.")
    return graph
