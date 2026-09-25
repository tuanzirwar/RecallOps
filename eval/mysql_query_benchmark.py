from __future__ import annotations
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from sqlalchemy import create_engine, event, insert, select, func
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
DATABASE = "mysql+pymysql://recallops:recallops@127.0.0.1:3306/recallops?charset=utf8mb4"
os.environ["RECALLOPS_DATABASE_URL"] = DATABASE
os.environ["RECALLOPS_TRUSTED_PROXY_TOKEN"] = "query-benchmark-token"
sys.path.insert(0, str(ROOT / "memory-service"))
from app.config import get_settings
from app.database import engine
from app.main import app
from app.models import Incident, IncidentService, Service, Tenant, Workspace, WorkspaceMember
from fastapi.testclient import TestClient

WORKSPACE = "query-bench-20260925"
TENANT = "query-bench-tenant"
HEADERS = {"x-proxy-token": "query-benchmark-token", "x-tenant-id": TENANT,
           "x-workspace-id": WORKSPACE, "x-user-id": "bench-user"}
QUERY = {"query": "PAYMENT_5032", "mode": "fts", "top_k": 5}


def seed(size=10000):
    with Session(engine) as db:
        if db.get(Workspace, WORKSPACE):
            count = db.scalar(select(func.count()).select_from(Incident).where(Incident.workspace_id == WORKSPACE))
            if count != size:
                raise RuntimeError(f"existing benchmark dataset has {count} rows, expected {size}")
            return count
        db.add(Tenant(id=TENANT, name="Query Benchmark"))
        db.flush()
        db.add(Workspace(id=WORKSPACE, tenant_id=TENANT, name="Query Benchmark Workspace"))
        db.flush()
        db.add(WorkspaceMember(workspace_id=WORKSPACE, user_open_id="bench-user", role="viewer"))
        db.add(Service(id=900001, tenant_id=TENANT, name="payment-service"))
        db.commit()
        for start in range(0, size, 1000):
            rows = [{"id": f"QBENCH-{i:05d}", "tenant_id": TENANT, "workspace_id": WORKSPACE,
                     "title": f"支付故障 {i}", "symptom": "支付接口超时", "root_cause": "payment-service 连接池耗尽",
                     "resolution": "调整连接池配置", "severity": "P2", "status": "active",
                     "error_codes": ["PAYMENT_5032"], "embedding": [0.0] * 96,
                     "created_by": "bench-user", "confirmed_by": "bench-user"}
                    for i in range(start, min(size, start + 1000))]
            db.execute(insert(Incident), rows)
            db.execute(insert(IncidentService), [{"incident_id": row["id"], "service_id": 900001,
                                                  "role": "affected"} for row in rows])
            db.commit()
        return size


def count_query(mode):
    settings = get_settings()
    settings.service_load_mode = mode
    count = 0
    def before_cursor(*_):
        nonlocal count
        count += 1
    event.listen(engine, "before_cursor_execute", before_cursor)
    try:
        with TestClient(app) as client:
            response = client.post("/v1/incidents/search", headers=HEADERS, json=QUERY)
            response.raise_for_status()
            return count, [item["incident_id"] for item in response.json()["results"]]
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor)


def http_latency(mode, requests=3):
    env = os.environ.copy()
    env.update(PYTHONPATH=str(ROOT / ".deps"), RECALLOPS_DATABASE_URL=DATABASE,
               RECALLOPS_TRUSTED_PROXY_TOKEN="query-benchmark-token",
               RECALLOPS_SERVICE_LOAD_MODE=mode)
    port = 8126 if mode == "n_plus_one" else 8127
    log = open(ROOT / "eval/reports" / f"mysql_query_{mode}.log", "w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                               cwd=ROOT / "memory-service", env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=120) as client:
            for _ in range(100):
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.RequestError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError("API startup failed")
            client.post("/v1/incidents/search", headers=HEADERS, json=QUERY).raise_for_status()
            latencies = []
            ids = []
            for _ in range(requests):
                started = time.perf_counter()
                response = client.post("/v1/incidents/search", headers=HEADERS, json=QUERY)
                response.raise_for_status()
                latencies.append(round((time.perf_counter() - started) * 1000, 2))
                ids = [item["incident_id"] for item in response.json()["results"]]
            return latencies, ids
    finally:
        process.terminate()
        process.wait(timeout=5)
        log.close()


def main():
    size = seed()
    output = {"environment": "MySQL 8.4, real HTTP, same 10K synthetic incidents, single client; 1 warmup + 3 measured requests per variant",
              "dataset_size": size, "variants": {}}
    for mode in ("n_plus_one", "batch"):
        sql_count, counted_ids = count_query(mode)
        times, http_ids = http_latency(mode)
        assert counted_ids == http_ids
        output["variants"][mode] = {"sql_count_testclient": sql_count,
                                      "http_latencies_ms": times,
                                      "http_mean_ms": round(sum(times) / len(times), 2),
                                      "result_ids": http_ids}
        print(mode, json.dumps(output["variants"][mode], ensure_ascii=False), flush=True)
    assert output["variants"]["n_plus_one"]["result_ids"] == output["variants"]["batch"]["result_ids"]
    (ROOT / "eval/reports/mysql_query_benchmark.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
