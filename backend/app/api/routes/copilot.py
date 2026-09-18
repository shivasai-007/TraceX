from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_investigator
from app.copilot.copilot_service import ask_about_investigation, summarize_investigation
from app.core.config import get_settings
from app.db.models import Case, Investigator, WalletInvestigation
from app.db.session import get_db

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


class AskRequest(BaseModel):
    question: str


def _load(investigation_id: str, db: Session, investigator: Investigator) -> WalletInvestigation:
    investigation = db.query(WalletInvestigation).filter_by(id=investigation_id).first()
    if not investigation:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Investigation not found.")
    case = db.query(Case).filter_by(id=investigation.case_id).first()
    if case.lead_investigator_id != investigator.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This investigation belongs to another investigator.")
    return investigation


@router.get("/status")
def status_():
    return {"available": get_settings().copilot_enabled}


@router.post("/{investigation_id}/summarize")
def summarize(
    investigation_id: str,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    investigation = _load(investigation_id, db, investigator)
    result = summarize_investigation(investigation)
    if result.get("available"):
        investigation.copilot_summary = result["summary"]
        db.commit()
    return result


@router.post("/{investigation_id}/ask")
def ask(
    investigation_id: str,
    payload: AskRequest,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    investigation = _load(investigation_id, db, investigator)
    return ask_about_investigation(investigation, payload.question)
