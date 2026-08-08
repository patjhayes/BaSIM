"""Celery configuration shared by API dispatch and compute workers."""

from __future__ import annotations

import os

from celery import Celery


BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "basim",
    broker=BROKER_URL,
    include=["src.worker.tasks"],
)
celery_app.conf.update(
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    broker_pool_limit=4,
    task_acks_late=True,
    task_ignore_result=True,
    task_serializer="json",
    timezone="UTC",
    worker_concurrency=int(os.environ.get("CELERY_CONCURRENCY", "2")),
    worker_prefetch_multiplier=1,
)