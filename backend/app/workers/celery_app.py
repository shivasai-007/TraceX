"""
Celery application (architecture diagram: the Workers plane).

Optional. When REDIS_URL is empty the API runs the pipeline inline via
FastAPI BackgroundTasks and Celery is never imported -- which is what
lets the whole stack run on a laptop with no broker installed.

Start a worker with (from backend/, venv active):
    celery -A app.workers.celery_app worker --loglevel=info
On Windows, add the solo pool, which Celery requires there:
    celery -A app.workers.celery_app worker --loglevel=info --pool=solo
"""
from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "tracex",
    broker=settings.redis_url or "memory://",
    backend=settings.redis_url or "cache+memory://",
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=1800,
)
