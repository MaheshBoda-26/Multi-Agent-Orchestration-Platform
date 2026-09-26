"""Celery application.

Redis is the broker only (locked decision D3). Late acknowledgement plus
`task_reject_on_worker_lost` means a killed worker's job is redelivered and the
graph resumes from its Postgres checkpoint instead of starting over.
"""
import os

from celery import Celery

celery_app = Celery(
    "orchestra",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # One in-flight job per worker slot so a crash loses at most that job.
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=3600,
    # Redis redelivers unacked messages after this many seconds.
    broker_transport_options={"visibility_timeout": 60},
)

celery_app.autodiscover_tasks(["worker"])
