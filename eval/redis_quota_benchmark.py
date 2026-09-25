from __future__ import annotations
import json
import math
import random
import time
import uuid
from pathlib import Path

import redis

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "memory-service"))
from app.quota import TOKEN_BUCKET, QuotaUnavailable, acquire
from app.config import get_settings

RATE = 8.0
CAPACITY = 8.0
DURATION = 4.0
OFFERED_PER_SECOND = 12
client = redis.Redis.from_url("redis://127.0.0.1:6379/0")


def run(workers: int, pattern: str):
    key = "recallops:quota-bench:" + uuid.uuid4().hex
    rng = random.Random(44)
    tokens = [CAPACITY / workers] * workers
    last = [0.0] * workers
    static_accepted = shared_accepted = offered = 0
    start = time.monotonic()
    schedule = [i / OFFERED_PER_SECOND for i in range(int(DURATION * OFFERED_PER_SECOND))]
    for offset in schedule:
        remaining = start + offset - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        elapsed = time.monotonic() - start
        if pattern == "uniform":
            worker = offered % workers
        elif pattern == "paused_worker":
            worker = offered % workers if elapsed < DURATION / 2 else 0
        else:
            worker = 0 if rng.random() < .9 else 1 + rng.randrange(workers - 1)
        refill = max(0.0, elapsed - last[worker]) * RATE / workers
        tokens[worker] = min(CAPACITY / workers, tokens[worker] + refill)
        last[worker] = elapsed
        if tokens[worker] >= 1:
            tokens[worker] -= 1
            static_accepted += 1
        shared_accepted += int(client.eval(TOKEN_BUCKET, 1, key, RATE, CAPACITY))
        offered += 1
    elapsed = time.monotonic() - start
    client.delete(key)
    bound = math.floor(CAPACITY + RATE * elapsed)
    return {"workers": workers, "pattern": pattern, "offered": offered,
            "static_accepted": static_accepted, "shared_accepted": shared_accepted,
            "static_utilization_percent": round(static_accepted / bound * 100, 1),
            "shared_utilization_percent": round(shared_accepted / bound * 100, 1),
            "allowed_bound": bound, "shared_over_limit": shared_accepted > bound,
            "elapsed_seconds": round(elapsed, 3)}


def main():
    runs = [run(workers, pattern) for workers in (2, 4)
            for pattern in ("uniform", "skewed", "paused_worker")]
    settings = get_settings()
    prior = settings.redis_url
    settings.redis_url = "redis://127.0.0.1:6399/0"
    try:
        try:
            acquire(timeout_seconds=.1)
            fail_closed = False
        except QuotaUnavailable:
            fail_closed = True
    finally:
        settings.redis_url = prior
    output = {"environment": "Redis 7.4 Lua atomic bucket, real elapsed time; static local split simulated with same aggregate rate/capacity",
              "rate_per_second": RATE, "capacity": CAPACITY,
              "duration_seconds": DURATION, "runs": runs,
              "redis_unavailable_fails_closed": fail_closed}
    (ROOT / "eval/reports/redis_quota_benchmark.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
