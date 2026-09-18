"""
Loads app/entity_intel/seed_data/known_addresses.json into the
KnownEntity table. Safe to re-run (upserts by chain+address).

Run with:  python -m app.db.seed_entities
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.models import KnownEntity  # noqa: E402
from app.db.session import Base, SessionLocal, engine  # noqa: E402

SEED_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "entity_intel", "seed_data", "known_addresses.json"
)


def seed_entities() -> None:
    Base.metadata.create_all(bind=engine)
    with open(SEED_PATH, encoding="utf-8") as f:
        data = json.load(f)

    db = SessionLocal()
    added, skipped = 0, 0
    try:
        for entry in data.get("entities", []):
            exists = (
                db.query(KnownEntity)
                .filter_by(chain=entry["chain"], address=entry["address"].lower())
                .first()
            )
            if exists:
                skipped += 1
                continue
            db.add(
                KnownEntity(
                    name=entry["name"],
                    entity_type=entry["entity_type"],
                    chain=entry["chain"],
                    address=entry["address"].lower(),
                    source=entry["source"],
                    source_date=entry.get("source_date"),
                    evidence=entry.get("evidence"),
                    confidence=entry.get("confidence", "attributed"),
                )
            )
            added += 1
        db.commit()
    finally:
        db.close()
    print(f"Known-entity seed: {added} added, {skipped} already present.")
    print("Add real intelligence feeds to seed_data/known_addresses.json -- see its _readme block.")


if __name__ == "__main__":
    seed_entities()
