from __future__ import annotations
import json
import os
import queue
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "memory-service"
DATABASE = "mysql+pymysql://recallops:recallops@127.0.0.1:3306/recallops?charset=utf8mb4"
sys.path.insert(0, str(SERVICE))
from app.models import Draft, ExtractionTask

class StubState:
    def __init__(self):
        self.lock = threading.Lock()
        self.hold_next = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

state = StubState()
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        self.rfile.read(length)
        with state.lock:
            state.calls += 1
            hold = state.hold_next
            state.hold_next = False
            if hold:
                state.entered.set()
        if hold:
            state.release.wait(timeout=15)
        incident = {"title": "支付超时", "symptom": "回调超时", "root_cause": "连接池耗尽",
                    "resolution": "扩容连接池", "severity": "P2", "error_codes": ["PAYMENT_5032"],
                    "services": [{"name": "payment-service", "role": "affected"}], "actions": []}
        body = json.dumps({"choices": [{"message": {"content": json.dumps(incident, ensure_ascii=False)}}]}, ensure_ascii=False).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
    def log_message(self, *args):
        pass


def worker(env, number):
    log = open(ROOT / "eval/reports" / f"rabbit_worker_{number}.log", "w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "-m", "app.queue", "worker"], cwd=SERVICE,
                               env=env, stdout=log, stderr=subprocess.STDOUT)
    return process, log


def wait_terminal(client, task_id, headers):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = client.get(f"/v1/extractions/{task_id}", headers=headers).json()
        if result["status"] in {"succeeded", "failed"}:
            return result
        time.sleep(.1)
    raise TimeoutError(task_id)


def main(count=20):
    server = ThreadingHTTPServer(("127.0.0.1", 8129), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    subprocess.run(["docker", "compose", "stop", "worker"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    env = os.environ.copy()
    env.update(PYTHONPATH=str(ROOT / ".deps"), RECALLOPS_DATABASE_URL=DATABASE,
               RECALLOPS_RABBITMQ_URL="amqp://guest:guest@127.0.0.1:5672/%2F",
               RECALLOPS_REDIS_URL="redis://127.0.0.1:6379/0",
               RECALLOPS_EXTRACTION_MODE="model", RECALLOPS_MODEL_BASE_URL="http://127.0.0.1:8129/v1",
               RECALLOPS_MODEL_API_KEY="stub", RECALLOPS_MODEL_NAME="fixed-response-stub",
               RECALLOPS_MODEL_QUOTA_RATE="100", RECALLOPS_MODEL_QUOTA_CAPACITY="100")
    suffix = uuid.uuid4().hex[:8]
    headers = {"x-proxy-token": "dev-proxy-token", "x-tenant-id": f"rabbit-{suffix}",
               "x-workspace-id": f"rabbit-ws-{suffix}", "x-user-id": f"rabbit-user-{suffix}"}
    outcomes = []
    current = None
    logs = []
    try:
        with httpx.Client(base_url="http://127.0.0.1:18000", timeout=10) as client:
            client.post("/dev/bootstrap", params={"x_proxy_token": "dev-proxy-token"}, json={
                "tenant_id": headers["x-tenant-id"], "workspace_id": headers["x-workspace-id"],
                "chat_id": f"rabbit-chat-{suffix}", "user_open_id": headers["x-user-id"],
                "role": "maintainer"}).raise_for_status()
            for i in range(count):
                state.entered.clear()
                state.release.clear()
                with state.lock:
                    state.hold_next = True
                response = client.post("/v1/extractions", headers=headers, json={
                    "thread_id": f"rabbit-{suffix}-{i}", "messages": [{
                        "message_id": f"rabbit-msg-{suffix}-{i}",
                        "source_url": f"https://example.test/rabbit/{suffix}/{i}",
                        "content": f"故障现象：支付超时 {i}"}]})
                response.raise_for_status()
                task_id = response.json()["task_id"]
                first, log1 = worker(env, f"{i}_before")
                logs.append(log1)
                if not state.entered.wait(timeout=10):
                    first.terminate()
                    raise TimeoutError("worker did not enter model call")
                first.terminate()
                first.wait(timeout=5)
                state.release.set()
                second, log2 = worker(env, f"{i}_after")
                logs.append(log2)
                current = second
                result = wait_terminal(client, task_id, headers)
                second.terminate()
                second.wait(timeout=5)
                current = None
                with Session(create_engine(DATABASE)) as db:
                    draft_count = db.scalar(select(func.count()).select_from(Draft).where(Draft.id == result.get("draft_id")))
                    task = db.get(ExtractionTask, task_id)
                    attempts = task.attempts
                outcomes.append({"task_id": task_id, "status": result["status"],
                                 "draft_count": draft_count, "attempts": attempts})
                print(f"recovered {i + 1}/{count}", flush=True)
        output = {"environment": "MySQL + durable RabbitMQ; real separate worker processes; fixed-response model HTTP stub",
                  "fault": "terminate worker after model request starts, before DB commit and ACK",
                  "count": count, "succeeded": sum(x["status"] == "succeeded" for x in outcomes),
                  "duplicate_drafts": sum(x["draft_count"] != 1 for x in outcomes),
                  "outcomes": outcomes, "model_http_calls": state.calls}
        (ROOT / "eval/reports/rabbit_recovery.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: v for k, v in output.items() if k != "outcomes"}, ensure_ascii=False))
    finally:
        if current and current.poll() is None:
            current.terminate()
            current.wait(timeout=5)
        state.release.set()
        server.shutdown()
        for log in logs:
            log.close()
        subprocess.run(["docker", "compose", "start", "worker"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)

if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20)
