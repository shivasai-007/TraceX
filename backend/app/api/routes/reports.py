from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_investigator
from app.db.models import Case, Investigator, WalletInvestigation
from app.db.session import get_db
from app.reporting.report_builder import build_report_payload, render_json, render_pdf

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _load(investigation_id: str, db: Session, investigator: Investigator) -> tuple[Case, WalletInvestigation]:
    investigation = db.query(WalletInvestigation).filter_by(id=investigation_id).first()
    if not investigation:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Investigation not found.")
    case = db.query(Case).filter_by(id=investigation.case_id).first()
    if case.lead_investigator_id != investigator.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This investigation belongs to another investigator.")
    if investigation.status != "complete":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This investigation is {investigation.status}. Reports are generated once a trace completes.",
        )
    return case, investigation


@router.get("/{investigation_id}/json")
def report_json(
    investigation_id: str,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    case, investigation = _load(investigation_id, db, investigator)
    return build_report_payload(case, investigation)


@router.get("/{investigation_id}/pdf")
def report_pdf(
    investigation_id: str,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    case, investigation = _load(investigation_id, db, investigator)
    payload = build_report_payload(case, investigation)
    pdf_bytes = render_pdf(payload)
    filename = f"TraceX_{case.case_number}_{investigation.address[:10]}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{investigation_id}/download.json")
def report_json_download(
    investigation_id: str,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    case, investigation = _load(investigation_id, db, investigator)
    payload = build_report_payload(case, investigation)
    filename = f"TraceX_{case.case_number}_{investigation.address[:10]}.json"
    return Response(
        content=render_json(payload),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
