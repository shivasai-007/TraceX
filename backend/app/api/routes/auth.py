from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_investigator
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import Investigator
from app.db.session import get_db
from app.schemas.auth import InvestigatorCreate, LoginRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    investigator = db.query(Investigator).filter_by(email=payload.email).first()
    if not investigator or not verify_password(payload.password, investigator.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect.")
    if not investigator.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deactivated.")
    token = create_access_token(
        subject=investigator.id,
        extra_claims={"badge_id": investigator.badge_id, "name": investigator.full_name},
    )
    return TokenResponse(
        access_token=token,
        investigator_name=investigator.full_name,
        investigator_id=investigator.id,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: InvestigatorCreate, db: Session = Depends(get_db)):
    if db.query(Investigator).filter_by(email=payload.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account already exists for this email.")
    if db.query(Investigator).filter_by(badge_id=payload.badge_id).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account already exists for this badge ID.")
    investigator = Investigator(
        badge_id=payload.badge_id,
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        unit=payload.unit,
    )
    db.add(investigator)
    db.commit()
    db.refresh(investigator)
    token = create_access_token(subject=investigator.id, extra_claims={"badge_id": investigator.badge_id})
    return TokenResponse(access_token=token, investigator_name=investigator.full_name, investigator_id=investigator.id)


@router.get("/me")
def me(investigator: Investigator = Depends(get_current_investigator)):
    return {
        "id": investigator.id,
        "badge_id": investigator.badge_id,
        "full_name": investigator.full_name,
        "email": investigator.email,
        "unit": investigator.unit,
    }
