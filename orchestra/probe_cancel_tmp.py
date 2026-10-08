"""Throwaway probe 7: set the broker by env var instead of attribute assignment."""
import os

os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/15"

from worker.celery_app import celery_app  # noqa: E402
from worker.tasks import run_task  # noqa: E402

print("broker_url:", celery_app.conf.broker_url)
print("conf.get  :", celery_app.conf.get("broker_url"))
print("pool conn :", celery_app.connection().as_uri())
print("task app  :", run_task.app.conf.get("broker_url"))
