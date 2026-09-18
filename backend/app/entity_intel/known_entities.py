"""
Entity Intelligence Database service: the query layer over KnownEntity
(see app/db/models.py + app/db/seed_entities.py for how it gets populated).
"""
from sqlalchemy.orm import Session

from app.db.models import KnownEntity


def all_entities(db: Session, chain: str | None = None) -> list[dict]:
    q = db.query(KnownEntity)
    if chain:
        q = q.filter(KnownEntity.chain == chain)
    return [
        {
            "id": e.id,
            "name": e.name,
            "entity_type": e.entity_type,
            "chain": e.chain.value if hasattr(e.chain, "value") else e.chain,
            "address": e.address,
            "source": e.source,
            "source_date": e.source_date,
            "evidence": e.evidence,
            "confidence": e.confidence,
        }
        for e in q.all()
    ]


def match_addresses(db: Session, addresses: set[str], chain: str | None = None) -> dict[str, dict]:
    """Returns {address: entity_dict} for every address in `addresses`
    that has a known-entity match."""
    entities = all_entities(db, chain)
    by_address = {e["address"]: e for e in entities}
    return {addr: by_address[addr] for addr in addresses if addr.lower() in by_address}
