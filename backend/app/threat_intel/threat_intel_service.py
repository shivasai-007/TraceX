"""
Threat Intelligence: enriches a trace with external malicious/scam/
ransomware address intelligence.

Feeds off the SAME Entity Intelligence DB as entity_intel/known_entities.py
(entity_type in {"scam", "ransomware"}) so there is one table, one seed
format, one place to load data -- see backend/app/entity_intel/seed_data/.

This is the "Enrichment Workers -> Threat Intelligence" path in the
architecture diagram. Real deployments should schedule
workers/enrichment_worker.py to periodically pull fresh exports from:
  - CryptoScamDB           https://cryptoscamdb.org            (scam addresses/URLs)
  - Chainabuse              https://chainabuse.com/api           (community-reported abuse, needs an API key)
  - BitcoinHeist / UCI      https://archive.ics.uci.edu/dataset/526 (ransomware addresses, static research dataset)
and upsert them into KnownEntity via app/db/seed_entities.py-style loaders.
No fabricated address lists ship with this build -- see the seed file's
_readme for why.
"""
from sqlalchemy.orm import Session

from app.db.models import KnownEntity

THREAT_TYPES = {"scam", "ransomware", "mixer"}


def assess_threat_exposure(db: Session, addresses: set[str], chain: str) -> dict:
    if not addresses:
        return {"hits": [], "exposure_score": 0.0}

    rows = (
        db.query(KnownEntity)
        .filter(KnownEntity.chain == chain, KnownEntity.address.in_(addresses))
        .filter(KnownEntity.entity_type.in_(THREAT_TYPES))
        .all()
    )
    hits = [
        {
            "address": r.address,
            "name": r.name,
            "entity_type": r.entity_type,
            "source": r.source,
            "confidence": r.confidence,
        }
        for r in rows
    ]
    # simple, explainable scoring: each confirmed hit weighs more than an inferred one
    weight = {"confirmed": 1.0, "attributed": 0.75, "inferred": 0.5, "observed": 0.35}
    exposure_score = min(1.0, sum(weight.get(h["confidence"], 0.5) for h in hits) / 3)
    return {"hits": hits, "exposure_score": round(exposure_score, 4)}
