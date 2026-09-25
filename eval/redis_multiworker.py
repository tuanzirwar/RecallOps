from __future__ import annotations
import json
import math
import multiprocessing as mp
import time
import uuid
from pathlib import Path
import redis

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "memory-service"))
from app.quota import TOKEN_BUCKET
RATE = 8.0
CAPACITY = 8.0
DURATION = 4.0
OFFERED = 48


def worker(worker_id, arrivals, start_at, key, rate, capacity, results):
    client = redis.Redis.from_url("redis://127.0.0.1:6379/0")
    passed = 0
    for offset in arrivals:
        remaining = start_at + offset - time.monotonic()
        if remaining > 0:
            time.sleep(remaining)
        passed += int(client.eval(TOKEN_BUCKET, 1, key if isinstance(key, str) else key[worker_id], rate, capacity))
    results.put((worker_id, passed))


def run(workers, pattern, allocation):
    if pattern == "uniform":
        assignments = [i % workers for i in range(OFFERED)]
    else:
        assignments = [0 if i % 10 != 9 else 1 + ((i // 10) % (workers - 1)) for i in range(OFFERED)]
    arrivals = [[i / 12 for i, assigned in enumerate(assignments) if assigned == worker_id]
                for worker_id in range(workers)]
    prefix = "recallops:multiworker:" + uuid.uuid4().hex
    keys = prefix if allocation == "shared" else [f"{prefix}:{i}" for i in range(workers)]
    rate = RATE if allocation == "shared" else RATE / workers
    capacity = CAPACITY if allocation == "shared" else CAPACITY / workers
    results = mp.Queue()
    start_at = time.monotonic() + .5
    processes = [mp.Process(target=worker, args=(i, arrivals[i], start_at, keys, rate, capacity, results))
                 for i in range(workers)]
    for process in processes:
        process.start()
    admitted = dict(results.get(timeout=15) for _ in processes)
    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0
    elapsed = max(0, time.monotonic() - start_at)
    client = redis.Redis.from_url("redis://127.0.0.1:6379/0")
    client.delete(*(keys if isinstance(keys, list) else [keys]))
    return {"workers": workers, "pattern": pattern, "allocation": allocation,
            "offered": OFFERED, "admitted": sum(admitted.values()),
            "per_worker": admitted, "global_bound": math.floor(CAPACITY + RATE * elapsed),
            "elapsed_seconds": round(elapsed, 3)}


def main():
    runs = [run(workers, pattern, allocation) for workers in (2, 4)
            for pattern in ("uniform", "skewed") for allocation in ("static", "shared")]
    output = {"environment": "2/4 real Python worker processes and Redis 7.4 Lua; equal aggregate token rate/capacity",
              "rate_per_second": RATE, "capacity": CAPACITY, "runs": runs}
    (ROOT / "eval/reports/redis_multiworker.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    mp.freeze_support()
    main()
