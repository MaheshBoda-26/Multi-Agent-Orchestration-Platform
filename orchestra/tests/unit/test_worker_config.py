from worker.celery_app import celery_app
from worker.tasks import initial_state


def test_worker_uses_late_acknowledgement():
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True


def test_worker_prefetches_one_job():
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_visibility_timeout_allows_redelivery_within_a_minute():
    assert celery_app.conf.broker_transport_options["visibility_timeout"] == 60


def test_initial_state_shape():
    state = initial_state("task-1", "do something")
    assert state["task_id"] == "task-1"
    assert state["results"] == {}
    assert state["plan"] is None
