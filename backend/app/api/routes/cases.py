from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_investigator
from app.db.models import Alert, Case, CaseNote, CaseStatus, Investigator, WalletInvestigation
from app.db.session import get_db
from app.schemas.case import CaseCreate, CaseNoteCreate, CaseOut

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _owned_case(case_id: str, db: Session, investigator: Investigator) -> Case:
    case = db.query(Case).filter_by(id=case_id).first()
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found.")
    if case.lead_investigator_id != investigator.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This case belongs to another investigator.")
    return case


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CaseCreate,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    if db.query(Case).filter_by(case_number=payload.case_number).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "A case with this number already exists.")
    case = Case(
        case_number=payload.case_number,
        crime_type=payload.crime_type,
        victim_complaint=payload.victim_complaint,
        lead_investigator_id=investigator.id,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


@router.get("", response_model=list[CaseOut])
def list_cases(
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    return (
        db.query(Case)
        .filter_by(lead_investigator_id=investigator.id)
        .order_by(Case.updated_at.desc())
        .all()
    )


@router.get("/{case_id}")
def get_case(
    case_id: str,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    case = _owned_case(case_id, db, investigator)
    wallets = db.query(WalletInvestigation).filter_by(case_id=case.id).order_by(WalletInvestigation.created_at.desc()).all()
    notes = db.query(CaseNote).filter_by(case_id=case.id).order_by(CaseNote.created_at.desc()).all()
    alerts = db.query(Alert).filter_by(case_id=case.id).order_by(Alert.created_at.desc()).all()
    return {
        "id": case.id,
        "case_number": case.case_number,
        "crime_type": case.crime_type,
        "victim_complaint": case.victim_complaint,
        "status": case.status.value,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "investigations": [
            {
                "id": w.id,
                "address": w.address,
                "chain": w.chain.value if hasattr(w.chain, "value") else w.chain,
                "status": w.status,
                "risk_score": (w.risk_result or {}).get("risk_score"),
                "risk_band": (w.risk_result or {}).get("risk_band"),
                "created_at": w.created_at,
            }
            for w in wallets
        ],
        "notes": [{"id": n.id, "body": n.body, "created_at": n.created_at} for n in notes],
        "alerts": [
            {
                "id": a.id,
                "alert_type": a.alert_type,
                "severity": a.severity,
                "message": a.message,
                "acknowledged": a.acknowledged,
                "created_at": a.created_at,
            }
            for a in alerts
        ],
    }


@router.patch("/{case_id}/status")
def update_status(
    case_id: str,
    new_status: CaseStatus,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    case = _owned_case(case_id, db, investigator)
    case.status = new_status
    db.commit()
    return {"id": case.id, "status": case.status.value}


@router.post("/{case_id}/notes", status_code=status.HTTP_201_CREATED)
def add_note(
    case_id: str,
    payload: CaseNoteCreate,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    case = _owned_case(case_id, db, investigator)
    note = CaseNote(case_id=case.id, author_id=investigator.id, body=payload.body)
    db.add(note)
    db.commit()
    db.refresh(note)
    return {"id": note.id, "body": note.body, "created_at": note.created_at}


@router.post("/{case_id}/alerts/{alert_id}/acknowledge")
def acknowledge_alert(
    case_id: str,
    alert_id: str,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    _owned_case(case_id, db, investigator)
    alert = db.query(Alert).filter_by(id=alert_id, case_id=case_id).first()
    if not alert:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found.")
    alert.acknowledged = True
    db.commit()
    return {"id": alert.id, "acknowledged": True}
