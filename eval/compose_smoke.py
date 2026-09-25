import json, time, uuid
from pathlib import Path
import httpx

root = Path(__file__).resolve().parents[1]
suffix = uuid.uuid4().hex[:8]
with httpx.Client(base_url="http://127.0.0.1:18000", timeout=20) as c:
    c.get("/health").raise_for_status()
    c.post("/dev/bootstrap", params={"x_proxy_token": "dev-proxy-token"}, json={
        "tenant_id": f"compose-{suffix}", "workspace_id": f"compose-ws-{suffix}",
        "chat_id": f"compose-chat-{suffix}", "user_open_id": f"compose-user-{suffix}",
        "role": "maintainer"}).raise_for_status()
    h = {"x-proxy-token": "dev-proxy-token", "x-tenant-id": f"compose-{suffix}",
         "x-workspace-id": f"compose-ws-{suffix}", "x-user-id": f"compose-user-{suffix}"}
    started = time.perf_counter()
    accepted = c.post("/v1/extractions", headers=h, json={"thread_id": f"compose-thread-{suffix}",
        "messages": [{"message_id": f"compose-msg-{suffix}", "source_url": f"https://example.test/{suffix}",
                      "content": "故障现象：数据库超时\n最终根因：连接池耗尽\n临时方案：提高连接数"}]})
    accepted.raise_for_status()
    accept_ms = (time.perf_counter() - started) * 1000
    task_id = accepted.json()["task_id"]
    for _ in range(100):
        result = c.get(f"/v1/extractions/{task_id}", headers=h).json()
        if result["status"] in {"succeeded", "failed"}:
            break
        time.sleep(.2)
    assert result["status"] == "succeeded", result
    finished_ms = (time.perf_counter() - started) * 1000
    commit = c.post("/v1/incidents", headers=h | {"x-request-id": f"compose-review-{suffix}"},
                    json={"draft_id": result["draft_id"], "confirm": True})
    commit.raise_for_status()
    output = {"deployment": "docker compose MySQL+RabbitMQ+Redis+API+Publisher+Worker",
              "extractor": "fixture", "accepted_p95_claim": None,
              "single_accept_ms": round(accept_ms, 1), "single_task_complete_ms": round(finished_ms, 1),
              "task_status": result["status"], "incident_id": commit.json()["incident_id"]}
    (root / "eval/reports/compose_smoke.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False))
