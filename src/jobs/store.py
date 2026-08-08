"""Redis persistence for analysis state, events, cancellation, and results."""

from __future__ import annotations

from datetime import datetime, timezone
import gzip
import json
import os
from typing import Any, Optional


DEFAULT_JOB_TTL_SECONDS = 24 * 60 * 60
MAX_JOB_EVENTS = 1000


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


class JobStore:
    def __init__(
        self,
        client: Any,
        ttl_seconds: int = DEFAULT_JOB_TTL_SECONDS,
    ) -> None:
        self.client = client
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _state_key(job_id: str) -> str:
        return f"job:{job_id}:state"

    @staticmethod
    def _events_key(job_id: str) -> str:
        return f"job:{job_id}:events"

    @staticmethod
    def _request_key(job_id: str) -> str:
        return f"job:{job_id}:request"

    @staticmethod
    def _result_key(job_id: str) -> str:
        return f"job:{job_id}:result"

    @staticmethod
    def _cancel_key(job_id: str) -> str:
        return f"job:{job_id}:cancel"

    @staticmethod
    def channel(job_id: str) -> str:
        return f"job:{job_id}:updates"

    def create_job(
        self,
        job_id: str,
        analysis_type: str,
        payload: dict[str, Any],
        *,
        user_id: Optional[str],
        project_code: Optional[str],
        cost: int,
    ) -> dict[str, Any]:
        timestamp = _utc_now()
        state = {
            "id": job_id,
            "analysis_type": analysis_type,
            "status": "queued",
            "progress": "0",
            "created_at": timestamp,
            "updated_at": timestamp,
            "user_id": user_id or "",
            "project_code": project_code or "",
            "cost": str(cost),
            "refunded": "0",
            "error": "",
        }
        request_bytes = gzip.compress(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        pipeline = self.client.pipeline(transaction=True)
        pipeline.hset(self._state_key(job_id), mapping=state)
        pipeline.set(self._request_key(job_id), request_bytes)
        pipeline.expire(self._state_key(job_id), self.ttl_seconds)
        pipeline.expire(self._request_key(job_id), self.ttl_seconds)
        pipeline.execute()
        self.append_event(
            job_id,
            {
                "type": "status",
                "status": "queued",
                "progress": 0,
            },
        )
        return self.get_job(job_id) or {}

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        raw_state = self.client.hgetall(self._state_key(job_id))
        if not raw_state:
            return None
        state = {_decode(key): _decode(value) for key, value in raw_state.items()}
        state["progress"] = int(state.get("progress", "0"))
        state["cost"] = int(state.get("cost", "0"))
        state["refunded"] = state.get("refunded") == "1"
        state["user_id"] = state.get("user_id") or None
        state["project_code"] = state.get("project_code") or None
        state["error"] = state.get("error") or None
        state["result_available"] = bool(
            self.client.exists(self._result_key(job_id))
        )
        return state

    def update_job(self, job_id: str, **fields: Any) -> Optional[dict[str, Any]]:
        if not self.client.exists(self._state_key(job_id)):
            return None
        mapping = {
            key: (
                "1"
                if value is True
                else "0"
                if value is False
                else ""
                if value is None
                else str(value)
            )
            for key, value in fields.items()
        }
        mapping["updated_at"] = _utc_now()
        pipeline = self.client.pipeline(transaction=True)
        pipeline.hset(self._state_key(job_id), mapping=mapping)
        pipeline.expire(self._state_key(job_id), self.ttl_seconds)
        pipeline.execute()
        return self.get_job(job_id)

    def append_event(self, job_id: str, event: dict[str, Any]) -> dict[str, Any]:
        event_payload = dict(event)
        event_payload.setdefault("timestamp", _utc_now())
        encoded = json.dumps(event_payload, separators=(",", ":"))
        pipeline = self.client.pipeline(transaction=True)
        pipeline.rpush(self._events_key(job_id), encoded)
        pipeline.ltrim(self._events_key(job_id), -MAX_JOB_EVENTS, -1)
        pipeline.expire(self._events_key(job_id), self.ttl_seconds)
        pipeline.publish(self.channel(job_id), encoded)
        pipeline.execute()
        return event_payload

    def get_events(self, job_id: str, start: int = 0) -> list[dict[str, Any]]:
        values = self.client.lrange(self._events_key(job_id), start, -1)
        return [json.loads(_decode(value)) for value in values]

    def get_request(self, job_id: str) -> Optional[dict[str, Any]]:
        value = self.client.get(self._request_key(job_id))
        if value is None:
            return None
        return json.loads(gzip.decompress(value).decode("utf-8"))

    def store_result(self, job_id: str, result: dict[str, Any]) -> None:
        encoded = gzip.compress(
            json.dumps(result, separators=(",", ":")).encode("utf-8")
        )
        self.client.setex(self._result_key(job_id), self.ttl_seconds, encoded)

    def get_result(self, job_id: str) -> Optional[dict[str, Any]]:
        value = self.client.get(self._result_key(job_id))
        if value is None:
            return None
        return json.loads(gzip.decompress(value).decode("utf-8"))

    def request_cancellation(self, job_id: str) -> bool:
        if not self.client.exists(self._state_key(job_id)):
            return False
        self.client.setex(self._cancel_key(job_id), self.ttl_seconds, "1")
        return True

    def is_cancelled(self, job_id: str) -> bool:
        return bool(self.client.exists(self._cancel_key(job_id)))


def get_job_store() -> JobStore:
    import redis

    redis_url = os.environ.get(
        "REDIS_URL",
        os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    )
    client = redis.Redis.from_url(redis_url, max_connections=4)
    ttl_seconds = int(
        os.environ.get("JOB_TTL_SECONDS", str(DEFAULT_JOB_TTL_SECONDS))
    )
    return JobStore(client, ttl_seconds=ttl_seconds)