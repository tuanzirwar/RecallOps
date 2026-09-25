from __future__ import annotations
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "memory-service"
TUI_CONFIG = Path(r"C:\mine soft\code\TUI\config.yaml")
config = yaml.safe_load(TUI_CONFIG.read_text(encoding="utf-8"))
provider = next(item for item in config["providers"]
                if item.get("protocol") == "openai" and item.get("wire_api") == "responses"
                and item.get("name") == "CloudVisit")
if not provider.get("api_key"):
    raise RuntimeError("TUI OpenAI Responses provider has no key")
ENV = os.environ.copy()
ENV.update(PYTHONPATH=str(ROOT / ".deps"),
           RECALLOPS_DATABASE_URL="mysql+pymysql://recallops:recallops@127.0.0.1:3306/recallops?charset=utf8mb4",
           RECALLOPS_RABBITMQ_URL="amqp://guest:guest@127.0.0.1:5672/%2F",
           RECALLOPS_REDIS_URL="redis://127.0.0.1:6379/0",
           RECALLOPS_EXTRACTION_MODE="model", RECALLOPS_MODEL_WIRE_API="responses",
           RECALLOPS_MODEL_BASE_URL=provider["base_url"],
           RECALLOPS_MODEL_API_KEY=provider["api_key"],
           RECALLOPS_MODEL_NAME=provider["model"],
           RECALLOPS_MODEL_TIMEOUT_SECONDS="120")
subprocess.run(["docker", "compose", "stop", "worker"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
log = open(ROOT / "eval/reports/real_model_worker.log", "w", encoding="utf-8")
worker = None
try:
    worker = subprocess.Popen([sys.executable, "-m", "app.queue", "worker"], cwd=SERVICE,
                              env=ENV, stdout=log, stderr=subprocess.STDOUT)
    with httpx.Client(base_url="http://127.0.0.1:18000", timeout=15) as client:
        suffix = uuid.uuid4().hex[:8]
        client.post("/dev/bootstrap", params={"x_proxy_token": "dev-proxy-token"}, json={
            "tenant_id": f"real-model-{suffix}", "workspace_id": f"real-model-ws-{suffix}",
            "chat_id": f"real-model-chat-{suffix}", "user_open_id": f"real-model-user-{suffix}",
            "role": "maintainer"}).raise_for_status()
        headers = {"x-proxy-token": "dev-proxy-token", "x-tenant-id": f"real-model-{suffix}",
                   "x-workspace-id": f"real-model-ws-{suffix}", "x-user-id": f"real-model-user-{suffix}"}
        started = time.perf_counter()
        accepted = client.post("/v1/extractions", headers=headers, json={
            "thread_id": f"real-model-thread-{suffix}", "messages": [
                {"message_id": f"real-model-msg-1-{suffix}",
                 "source_url": f"https://example.test/real-model/{suffix}/1",
                 "content": "10:00 payment-service 支付回调持续超时，出现 PAYMENT_5032。有人猜测是上游网络问题。"},
                {"message_id": f"real-model-msg-2-{suffix}",
                 "source_url": f"https://example.test/real-model/{suffix}/2",
                 "content": "10:20 排查连接池指标后确认：数据库连接池耗尽，等待队列积压。临时将 max_pool_size 从 50 提高到 200，回调恢复。长期行动：增加连接池水位告警。"}
            ]})
        accepted.raise_for_status()
        accept_ms = (time.perf_counter() - started) * 1000
        task_id = accepted.json()["task_id"]
        for _ in range(180):
            result = client.get(f"/v1/extractions/{task_id}", headers=headers).json()
            if result["status"] in {"succeeded", "failed"}:
                break
            time.sleep(1)
        else:
            raise TimeoutError("real model task did not finish in 180 seconds")
        elapsed_ms = (time.perf_counter() - started) * 1000
        output = {"model": provider["model"], "provider": "CloudVisit Responses",
                  "source": "synthetic incident, TUI local config; key not copied to report",
                  "task_id": task_id, "status": result["status"],
                  "accept_ms": round(accept_ms, 1), "complete_ms": round(elapsed_ms, 1),
                  "attempts": result["attempts"],
                  "fields_present": sorted(result.get("incident", {}).keys()),
                  "last_error": result.get("last_error")}
        (ROOT / "eval/reports/real_model_smoke.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(output, ensure_ascii=False))
        if result["status"] != "succeeded":
            raise RuntimeError("real model extraction failed")
finally:
    if worker is not None:
        worker.terminate()
        worker.wait(timeout=5)
    log.close()
    subprocess.run(["docker", "compose", "start", "worker"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
