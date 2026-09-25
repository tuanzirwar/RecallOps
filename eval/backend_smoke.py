from __future__ import annotations
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pika

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "memory-service"
BASE = "http://127.0.0.1:8123"
ENV = os.environ.copy()
ENV["PYTHONPATH"] = str(ROOT / ".deps")
ENV["RECALLOPS_DATABASE_URL"] = "mysql+pymysql://recallops:recallops@127.0.0.1:3306/recallops?charset=utf8mb4"
ENV["RECALLOPS_TRUSTED_PROXY_TOKEN"] = "smoke-proxy-token"
ENV["RECALLOPS_RABBITMQ_URL"] = "amqp://guest:guest@127.0.0.1:5672/%2F"
ENV["RECALLOPS_REDIS_URL"] = "redis://127.0.0.1:6379/0"
ENV["RECALLOPS_EXTRACTION_MODE"] = "fixture"


def launch(args: list[str], name: str):
    log = open(ROOT / "eval" / "reports" / f"backend_smoke_{name}.log", "w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, *args], cwd=SERVICE, env=ENV,
                               stdout=log, stderr=subprocess.STDOUT)
    return process, log


def main():
    processes = []
    started = time.perf_counter()
    try:
        processes.append(launch(["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8123"], "api"))
        client = httpx.Client(base_url=BASE, timeout=10)
        for _ in range(100):
            try:
                if client.get("/health").status_code == 200:
                    break
            except httpx.RequestError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("API did not start")
        suffix = uuid.uuid4().hex[:8]
        bootstrap = client.post("/dev/bootstrap", params={"x_proxy_token": "smoke-proxy-token"},
                                json={"tenant_id": f"tenant-{suffix}", "workspace_id": f"ws-{suffix}",
                                      "chat_id": f"chat-{suffix}", "user_open_id": f"user-{suffix}", "role": "maintainer"})
        bootstrap.raise_for_status()
        headers = {"x-proxy-token": "smoke-proxy-token", "x-tenant-id": f"tenant-{suffix}",
                   "x-workspace-id": f"ws-{suffix}", "x-user-id": f"user-{suffix}"}
        body = {"thread_id": f"thread-{suffix}", "messages": [{"message_id": f"msg-{suffix}",
                "source_url": f"https://example.test/{suffix}", "content": "故障现象：支付回调超时\n最终根因：payment-service 连接池耗尽\n临时方案：扩容连接池\n错误 PAYMENT_5032"}]}
        submitted = client.post("/v1/extractions", headers=headers, json=body)
        submitted.raise_for_status()
        task_id = submitted.json()["task_id"]
        time.sleep(1)
        before = client.get(f"/v1/extractions/{task_id}", headers=headers).json()
        assert before["status"] == "queued"
        processes.append(launch(["-m", "app.queue", "publisher"], "publisher"))
        processes.append(launch(["-m", "app.queue", "worker"], "worker"))
        for _ in range(100):
            result = client.get(f"/v1/extractions/{task_id}", headers=headers).json()
            if result["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.2)
        assert result["status"] == "succeeded", result
        conn = pika.BlockingConnection(pika.URLParameters(ENV["RECALLOPS_RABBITMQ_URL"]))
        channel = conn.channel()
        channel.basic_publish(exchange="", routing_key="recallops.extract.v1",
                              body=json.dumps({"task_id": task_id}).encode(),
                              properties=pika.BasicProperties(delivery_mode=2))
        conn.close()
        time.sleep(1)
        duplicate = client.get(f"/v1/extractions/{task_id}", headers=headers).json()
        assert duplicate["attempts"] == 1
        review = client.post("/v1/incidents", headers=headers | {"x-request-id": f"review-{suffix}"},
                             json={"draft_id": result["draft_id"], "confirm": True,
                                   "corrections": {"root_cause": "payment-service 数据库连接池耗尽"}})
        review.raise_for_status()
        incident_id = review.json()["incident_id"]
        detail = client.get(f"/v1/incidents/{incident_id}", headers=headers)
        detail.raise_for_status()
        search = client.post("/v1/incidents/search", headers=headers,
                             json={"query": "PAYMENT_5032", "mode": "fts"})
        search.raise_for_status()
        assert any(item["incident_id"] == incident_id for item in search.json()["results"])
        report = {"database": "mysql 8.4", "queue": "rabbitmq 3.13", "extractor": "fixture",
                  "api": "real HTTP on localhost", "task_id": task_id, "queued_before_publisher": before["status"],
                  "task_final": result["status"], "duplicate_delivery_attempts": duplicate["attempts"],
                  "incident_id": incident_id, "revision_count": len(detail.json()["revisions"]),
                  "search_found": True, "elapsed_ms": round((time.perf_counter() - started) * 1000, 1)}
        output = ROOT / "eval" / "reports" / "backend_smoke.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
    finally:
        for process, log in reversed(processes):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            log.close()


if __name__ == "__main__":
    main()
