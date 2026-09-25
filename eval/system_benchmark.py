"""RecallOps API 并发与 request_id 幂等压力测试。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".deps"))
sys.path.insert(0, str(ROOT / "memory-service"))


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return round(ordered[max(0, int(len(ordered) * fraction) - 1)], 3)


def _pool_checked_out(engine) -> int:
    checkedout = getattr(engine.pool, "checkedout", None)
    return int(checkedout()) if callable(checkedout) else 0


def _write(rows: list[dict[str, object]], output: Path, name: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{name}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    headers = list(rows[0])
    lines = [f"# {name}", "", "| " + " | ".join(headers) + " |"]
    lines.append("|" + "---|" * len(headers))
    lines.extend(
        "| " + " | ".join(str(row[key]) for key in headers) + " |"
        for row in rows
    )
    (output / f"{name}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--requests-per-level", type=int, default=200)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    database = (args.output / "benchmark.sqlite3").resolve().as_posix()
    os.environ["RECALLOPS_DATABASE_URL"] = f"sqlite:///{database}"
    os.environ["RECALLOPS_TRUSTED_PROXY_TOKEN"] = "benchmark-token"

    from app.database import Base, SessionLocal, engine
    from app.main import app
    from app.models import Incident, Tenant, Workspace, WorkspaceMember
    from app.retrieval import embed
    from fastapi.testclient import TestClient

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(Tenant(id="tenant-demo", name="Benchmark"))
        db.add(
            Workspace(
                id="workspace-demo", tenant_id="tenant-demo", name="Benchmark"
            )
        )
        db.add(
            WorkspaceMember(
                workspace_id="workspace-demo",
                user_open_id="ou_maintainer",
                role="maintainer",
            )
        )
        for index in range(160):
            text = f"订单错误 ERR_{index:03d} 服务 service_{index % 20:02d} 连接池耗尽"
            db.add(
                Incident(
                    id=f"seed-{index:03d}", tenant_id="tenant-demo",
                    workspace_id="workspace-demo", title=text, symptom=text,
                    root_cause="连接池耗尽", resolution="扩大连接池并限流",
                    severity="sev2", status="active", error_codes=[f"ERR_{index:03d}"],
                    embedding=embed(text), index_status="ready", created_by="benchmark",
                    confirmed_by="benchmark",
                )
            )
        db.commit()

    headers = {
        "x-proxy-token": "benchmark-token", "x-tenant-id": "tenant-demo",
        "x-workspace-id": "workspace-demo", "x-user-id": "ou_maintainer",
    }
    concurrency_rows: list[dict[str, object]] = []
    idempotency_rows: list[dict[str, object]] = []
    tracemalloc.start()
    with TestClient(app, raise_server_exceptions=False) as client:
        for concurrency in (1, 10, 50, 100, 200):
            request_count = max(args.requests_per_level, concurrency)
            tracemalloc.reset_peak()
            cpu_started = time.process_time()
            started = time.perf_counter()

            def search(index: int) -> tuple[int, float]:
                one = time.perf_counter()
                response = client.post(
                    "/v1/incidents/search",
                    headers=headers,
                    json={
                        "query": f"ERR_{index % 160:03d}",
                        "mode": "hybrid",
                        "top_k": 5,
                    },
                )
                return response.status_code, (time.perf_counter() - one) * 1000

            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(search, index) for index in range(request_count)]
                max_connections = 0
                while True:
                    done, pending = wait(futures, timeout=0.005)
                    max_connections = max(max_connections, _pool_checked_out(engine))
                    if not pending:
                        break
            results = [future.result() for future in futures]
            elapsed = time.perf_counter() - started
            cpu_seconds = time.process_time() - cpu_started
            latencies = [latency for _, latency in results]
            _, peak_memory = tracemalloc.get_traced_memory()
            errors = sum(code >= 400 for code, _ in results)
            concurrency_rows.append(
                {
                    "concurrency": concurrency, "requests": request_count,
                    "qps": round(request_count / elapsed, 3),
                    "p50_ms": _percentile(latencies, 0.50),
                    "p95_ms": _percentile(latencies, 0.95),
                    "p99_ms": _percentile(latencies, 0.99),
                    "error_rate": round(errors / request_count, 6),
                    "cpu_percent_normalized": round(
                        cpu_seconds / elapsed / max(1, os.cpu_count() or 1) * 100, 3
                    ),
                    "python_peak_memory_bytes": peak_memory,
                    "db_connections_peak": max_connections,
                }
            )
            _write(concurrency_rows, args.output, "concurrency")

        for concurrency in (2, 10, 100):
            draft = client.post(
                "/v1/drafts", headers=headers,
                json={
                    "thread_id": f"idempotency-{concurrency}",
                    "messages": [{
                        "message_id": f"message-{concurrency}",
                        "source_url": f"https://example.test/{concurrency}",
                        "content": (
                            f"故障现象：并发 {concurrency} 写入；最终根因：连接池耗尽；"
                            "临时方案：扩容；长期行动：限流；影响 order-service"
                        ),
                    }],
                },
            ).json()
            request_headers = headers | {"x-request-id": f"same-{concurrency}"}

            def commit(
                _: int,
                selected_headers=request_headers,
                draft_id=draft["draft_id"],
            ):
                return client.post(
                    "/v1/incidents",
                    headers=selected_headers,
                    json={"draft_id": draft_id, "confirm": True},
                )

            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=concurrency) as pool:
                responses = list(pool.map(commit, range(concurrency)))
            ids = {
                item.json().get("incident_id")
                for item in responses
                if item.status_code in {200, 201}
            }
            with SessionLocal() as db:
                official = (
                    db.query(Incident).filter(Incident.id.in_(ids)).count()
                    if ids
                    else 0
                )
            idempotency_rows.append(
                {
                    "concurrency": concurrency,
                    "submissions": concurrency,
                    "success_responses": sum(
                        item.status_code in {200, 201} for item in responses
                    ),
                    "unique_incident_ids": len(ids),
                    "official_incidents": official,
                    "exactly_once": len(ids) == 1 and official == 1,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                }
            )
            _write(idempotency_rows, args.output, "idempotency")
    tracemalloc.stop()
    _write(concurrency_rows, args.output, "concurrency")
    _write(idempotency_rows, args.output, "idempotency")
    print(
        json.dumps(
            {"concurrency": concurrency_rows, "idempotency": idempotency_rows},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
