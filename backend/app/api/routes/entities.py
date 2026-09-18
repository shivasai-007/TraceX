"""Entity Intelligence DB routes: browse and extend the known-address table."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_investigator
from app.db.models import Investigator, KnownEntity
from app.db.session import get_db
from app.entity_intel.known_entities import all_entities

router = APIRouter(prefix="/api/entities", tags=["entities"])


class EntityCreate(BaseModel):
    name: str
    entity_type: str  # vasp|exchange|dex|mixer|bridge|custodian|scam|ransomware
    chain: str
    address: str
    source: str
    source_date: str | None = None
    evidence: str | None = None
    confidence: str = "attributed"  # observed|inferred|attributed|confirmed


@router.get("")
def list_entities(
    chain: str | None = None,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    return all_entities(db, chain)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_entity(
    payload: EntityCreate,
    db: Session = Depends(get_db),
    investigator: Investigator = Depends(get_current_investigator),
):
    """Add a confirmed attribution back into the intelligence database.
    This is how a closed case feeds the next one: once an exchange confirms
    an address through legal process, record it here with confidence
    'confirmed' and the response reference as the source."""
    existing = db.query(KnownEntity).filter_by(chain=payload.chain, address=payload.address.lower()).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "This address is already in the intelligence database.")
    entity = KnownEntity(
        name=payload.name,
        entity_type=payload.entity_type,
        chain=payload.chain,
        address=payload.address.lower(),
        source=payload.source,
        source_date=payload.source_date,
        evidence=payload.evidence,
        confidence=payload.confidence,
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return {"id": entity.id, "name": entity.name, "address": entity.address}
