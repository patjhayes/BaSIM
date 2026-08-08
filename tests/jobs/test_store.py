from __future__ import annotations

from collections import defaultdict

from src.jobs.store import JobStore


class FakePipeline:
    def __init__(self, client: "FakeRedis") -> None:
        self.client = client
        self.operations = []

    def __getattr__(self, name):
        def queue(*args, **kwargs):
            self.operations.append((name, args, kwargs))
            return self

        return queue

    def execute(self):
        results = []
        for name, args, kwargs in self.operations:
            results.append(getattr(self.client, name)(*args, **kwargs))
        return results


class FakeRedis:
    def __init__(self) -> None:
        self.hashes = {}
        self.values = {}
        self.lists = defaultdict(list)
        self.expires = {}
        self.published = []

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    def hset(self, key, mapping):
        self.hashes.setdefault(key, {}).update(mapping)
        return len(mapping)

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def set(self, key, value):
        self.values[key] = value
        return True

    def setex(self, key, ttl, value):
        self.values[key] = value
        self.expires[key] = ttl
        return True

    def get(self, key):
        return self.values.get(key)

    def exists(self, key):
        return int(key in self.hashes or key in self.values or key in self.lists)

    def expire(self, key, ttl):
        self.expires[key] = ttl
        return True

    def rpush(self, key, value):
        self.lists[key].append(value)
        return len(self.lists[key])

    def ltrim(self, key, start, end):
        values = self.lists[key]
        start = max(0, len(values) + start) if start < 0 else start
        end = len(values) + end if end < 0 else end
        self.lists[key] = values[start : end + 1]
        return True

    def lrange(self, key, start, end):
        values = self.lists[key]
        end = len(values) + end if end < 0 else end
        return values[start : end + 1]

    def publish(self, channel, value):
        self.published.append((channel, value))
        return 1


def test_job_lifecycle_is_recoverable_from_redis() -> None:
    redis = FakeRedis()
    store = JobStore(redis, ttl_seconds=120)
    request = {"latitude": -31.95, "durations_minutes": [30]}

    created = store.create_job(
        "job-1",
        "design",
        request,
        user_id="user-1",
        project_code="PROJECT",
        cost=1,
    )

    assert created["status"] == "queued"
    assert created["progress"] == 0
    assert created["result_available"] is False
    assert store.get_request("job-1") == request
    assert store.get_events("job-1")[0]["status"] == "queued"

    store.update_job("job-1", status="running", progress=25)
    store.append_event(
        "job-1",
        {"type": "progress", "status": "running", "progress": 25},
    )
    store.store_result("job-1", {"model_runs": [{"peak_depth_m": 0.1431}]})
    store.update_job("job-1", status="completed", progress=100)

    completed = store.get_job("job-1")
    assert completed is not None
    assert completed["status"] == "completed"
    assert completed["progress"] == 100
    assert completed["result_available"] is True
    assert store.get_result("job-1") == {
        "model_runs": [{"peak_depth_m": 0.1431}]
    }
    assert redis.values["job:job-1:result"].startswith(b"\x1f\x8b")
    assert redis.published[-1][0] == "job:job-1:updates"
    assert all(ttl == 120 for ttl in redis.expires.values())


def test_cancellation_and_missing_jobs() -> None:
    redis = FakeRedis()
    store = JobStore(redis)

    assert store.get_job("missing") is None
    assert store.request_cancellation("missing") is False

    store.create_job(
        "job-2",
        "clogging",
        {},
        user_id=None,
        project_code=None,
        cost=0,
    )
    assert store.is_cancelled("job-2") is False
    assert store.request_cancellation("job-2") is True
    assert store.is_cancelled("job-2") is True