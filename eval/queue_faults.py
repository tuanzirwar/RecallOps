from __future__ import annotations
import json
import subprocess
import time
import uuid
from pathlib import Path
import httpx
import pika
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "memory-service"))
from app.models import Draft, ExtractionTask, OutboxEvent
DB = "mysql+pymysql://recallops:recallops@127.0.0.1:3306/recallops?charset=utf8mb4"

def compose(*args):
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)

def submit_batch(client, headers, prefix, count):
    ids = []
    for i in range(count):
        response = client.post("/v1/extractions", headers=headers, json={
            "thread_id": f"{prefix}-{i}", "messages": [{"message_id": f"msg-{prefix}-{i}",
            "source_url": f"https://example.test/{prefix}/{i}",
            "content": f"故障现象：队列故障 {prefix} {i}\n最终根因：连接池耗尽\n临时方案：扩容"}]})
        response.raise_for_status()
        ids.append(response.json()["task_id"])
    return ids

def wait_all(client, headers, ids, seconds=40):
    started = time.perf_counter()
    deadline = started + seconds
    while time.perf_counter() < deadline:
        rows = [client.get(f"/v1/extractions/{task_id}", headers=headers).json() for task_id in ids]
        if all(row["status"] in ("succeeded", "failed") for row in rows):
            return rows, round((time.perf_counter() - started) * 1000, 1)
        time.sleep(.2)
    raise TimeoutError("tasks did not reach terminal states")

def main(count=20):
    suffix = uuid.uuid4().hex[:8]
    headers = {"x-proxy-token": "dev-proxy-token", "x-tenant-id": f"fault-{suffix}",
               "x-workspace-id": f"fault-ws-{suffix}", "x-user-id": f"fault-user-{suffix}"}
    engine = create_engine(DB)
    output = {"environment": "Docker Compose MySQL + RabbitMQ + fixture worker, real HTTP", "cases": {}}
    publisher_stopped = broker_stopped = False
    try:
        with httpx.Client(base_url="http://127.0.0.1:18000", timeout=20) as client:
            client.post("/dev/bootstrap", params={"x_proxy_token": "dev-proxy-token"}, json={
                "tenant_id": headers["x-tenant-id"], "workspace_id": headers["x-workspace-id"],
                "chat_id": f"fault-chat-{suffix}", "user_open_id": headers["x-user-id"],
                "role": "maintainer"}).raise_for_status()
            compose("stop", "publisher")
            publisher_stopped = True
            pending_ids = submit_batch(client, headers, f"outbox-{suffix}", count)
            with Session(engine) as db:
                pending = db.scalar(select(func.count()).select_from(OutboxEvent).where(
                    OutboxEvent.task_id.in_(pending_ids), OutboxEvent.status == "pending"))
            compose("start", "publisher")
            publisher_stopped = False
            rows, recovery_ms = wait_all(client, headers, pending_ids)
            output["cases"]["db_committed_before_publish"] = {
                "accepted": count, "pending_outbox_before_restart": pending,
                "succeeded": sum(x["status"] == "succeeded" for x in rows),
                "recovery_ms": recovery_ms}
            attempts_before = {row["task_id"]: row["attempts"] for row in rows}
            conn = pika.BlockingConnection(pika.URLParameters("amqp://guest:guest@127.0.0.1:5672/%2F"))
            channel = conn.channel()
            for task_id in pending_ids:
                channel.basic_publish(exchange="", routing_key="recallops.extract.v1",
                                      body=json.dumps({"task_id": task_id}).encode(),
                                      properties=pika.BasicProperties(delivery_mode=2))
            conn.close()
            time.sleep(2)
            after = [client.get(f"/v1/extractions/{task_id}", headers=headers).json() for task_id in pending_ids]
            duplicate_results = sum(row["attempts"] != attempts_before[row["task_id"]] for row in after)
            output["cases"]["duplicate_after_result_commit"] = {
                "redelivered": count, "tasks_reprocessed": duplicate_results,
                "succeeded": sum(x["status"] == "succeeded" for x in after)}
            compose("stop", "rabbitmq")
            broker_stopped = True
            broker_ids = submit_batch(client, headers, f"broker-{suffix}", count)
            before = [client.get(f"/v1/extractions/{task_id}", headers=headers).json() for task_id in broker_ids]
            compose("start", "rabbitmq")
            broker_stopped = False
            rows, recovery_ms = wait_all(client, headers, broker_ids, seconds=60)
            output["cases"]["broker_restart"] = {
                "accepted": count, "queued_during_outage": sum(x["status"] == "queued" for x in before),
                "succeeded": sum(x["status"] == "succeeded" for x in rows),
                "recovery_ms": recovery_ms}
        (ROOT / "eval/reports/queue_faults.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(output, ensure_ascii=False))
    finally:
        if broker_stopped:
            compose("start", "rabbitmq")
        if publisher_stopped:
            compose("start", "publisher")

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20)
