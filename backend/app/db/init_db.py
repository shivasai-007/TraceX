"""
Creates tables and an initial investigator account.

Run with:  python -m app.db.init_db
(from backend/, with the virtualenv active)

This uses SQLAlchemy's create_all() rather than Alembic migrations to
keep the MVP zero-friction on a fresh checkout. Swap in Alembic once the
schema stabilizes -- see IMPLEMENTATION.md "Next steps".
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.security import hash_password  # noqa: E402
from app.db.models import Investigator  # noqa: E402
from app.db.session import Base, SessionLocal, engine  # noqa: E402


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        existing = db.query(Investigator).filter_by(email="admin@tracex.local").first()
        if not existing:
            demo = Investigator(
                badge_id="DEMO-0001",
                full_name="Demo Investigator",
                email="admin@tracex.local",
                hashed_password=hash_password("ChangeMe123!"),
                unit="Cyber Crime Cell",
            )
            db.add(demo)
            db.commit()
            print("Created default investigator: admin@tracex.local / ChangeMe123!  (change this password)")
        else:
            print("Database already initialized.")
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
