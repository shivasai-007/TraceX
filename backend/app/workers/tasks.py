"""
Background tasks. These mirror the four worker types in the architecture
diagram: ingestion, detection, enrichment and report workers.

Right now the investigation task runs the whole pipeline in one unit of
work, which is the correct shape for an MVP -- splitting it into four
separately-queued stages is worth doing when trace volume justifies it,
not before.
"""
from app.db.session import SessionLocal
from app.orchestrator.case_orchestrator import run_investigation_sync
from app.workers.celery_app import celery_app


@celery_app.task(name="tracex.run_investigation")
def run_investigation_task(investigation_id: str) -> dict:
    from app.db.models import WalletInvestigation

    db = SessionLocal()
    try:
        investigation = db.query(WalletInvestigation).filter_by(id=investigation_id).first()
        if not investigation:
            return {"status": "not_found", "investigation_id": investigation_id}
        run_investigation_sync(db, investigation)
        return {"status": investigation.status, "investigation_id": investigation_id}
    finally:
        db.close()


@celery_app.task(name="tracex.refresh_threat_intel")
def refresh_threat_intel_task() -> dict:
    """Enrichment worker placeholder.

    Wire this to scheduled pulls from CryptoScamDB / Chainabuse / your own
    confirmed-attribution exports, upserting into KnownEntity. Left as a
    named stub rather than a fake implementation because the right source
    list depends on which feeds your unit is licensed to use -- see
    backend/app/entity_intel/seed_data/known_addresses.json.
    """
    return {"status": "not_configured", "detail": "Add your intelligence feed loaders here."}
