"""Shared FastAPI dependencies: DB session + current investigator from JWT."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.models import Investigator
from app.db.session import get_db

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_investigator(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Investigator:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired. Sign in again.")
    investigator = db.query(Investigator).filter_by(id=payload.get("sub")).first()
    if not investigator or not investigator.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This account is no longer active.")
    return investigator
