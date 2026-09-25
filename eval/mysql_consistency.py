from __future__ import annotations
import concurrent.futures
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8124"
DATABASE = "mysql+pymysql://recallops:recallops@127.0.0.1:3306/recallops?charset=utf8mb4"
ENV = os.environ.copy()
ENV.update(PYTHONPATH=str(ROOT / ".deps"), RECALLOPS_DATABASE_URL=DATABASE,
           RECALLOPS_TRUSTED_PROXY_TOKEN="experiment-token")


def main():
    log = open(ROOT / "eval/reports/mysql_consistency_api.log", "w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8124"],
                               cwd=ROOT / "memory-service", env=ENV, stdout=log, stderr=subprocess.STDOUT)
    try:
        with httpx.Client(base_url=BASE, timeout=40, limits=httpx.Limits(max_connections=120)) as client:
            for _ in range(100):
                try:
                    if client.get("/health").status_code == 200:
                        break
                except httpx.RequestError:
                    pass
                time.sleep(.1)
            else:
                raise RuntimeError("API did not start")
            suffix = uuid.uuid4().hex[:8]
            client.post("/dev/bootstrap", params={"x_proxy_token": "experiment-token"},
                        json={"tenant_id": f"tenant-{suffix}", "workspace_id": f"ws-{suffix}",
                              "chat_id": f"chat-{suffix}", "user_open_id": f"user-{suffix}", "role": "maintainer"}).raise_for_status()
            headers = {"x-proxy-token": "experiment-token", "x-tenant-id": f"tenant-{suffix}",
                       "x-workspace-id": f"ws-{suffix}", "x-user-id": f"user-{suffix}"}
            engine = create_engine(DATABASE)
            from sys import path
            path.insert(0, str(ROOT / "memory-service"))
            from app.models import Incident, Revision, Source, RequestRecord
            results = []
            for concurrency in (2, 10, 100):
                thread = f"thread-{suffix}-{concurrency}"
                draft = client.post("/v1/drafts", headers=headers, json={"thread_id": thread,
                    "messages": [{"message_id": thread, "source_url": f"https://example.test/{thread}",
                                  "content": "故障现象：并发审核\n最终根因：连接池耗尽\n临时方案：扩容"}]}).json()["draft_id"]
                request_id = f"review-{thread}"
                def send(_):
                    try:
                        response = client.post("/v1/incidents", headers=headers | {"x-request-id": request_id},
                                               json={"draft_id": draft, "confirm": True})
                        return response.status_code, response.json()
                    except Exception as exc:
                        return 0, {"error": str(exc)}
                started = time.perf_counter()
                with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                    responses = list(pool.map(send, range(concurrency)))
                elapsed = time.perf_counter() - started
                ids = [value.get("incident_id") for code, value in responses if code in (200, 201)]
                with Session(engine) as db:
                    incident_count = db.scalar(select(func.count()).select_from(Incident).where(Incident.origin_draft_id == draft))
                    source_count = db.scalar(select(func.count()).select_from(Source).where(Source.incident_id.in_(ids or [""])))
                    record = db.get(RequestRecord, request_id)
                results.append({"concurrency": concurrency, "requests": concurrency,
                                "success": sum(code in (200, 201) for code, _ in responses),
                                "conflict": sum(code == 409 for code, _ in responses),
                                "server_error": sum(code >= 500 or code == 0 for code, _ in responses),
                                "incident_count": incident_count, "source_count": source_count,
                                "same_response": len(set(ids)) == 1 if ids else False,
                                "request_record_committed": record is not None,
                                "elapsed_ms": round(elapsed * 1000, 1)})
            conflict = client.post("/v1/incidents", headers=headers | {"x-request-id": request_id},
                                   json={"draft_id": draft, "confirm": True, "corrections": {"title": "changed"}})
            client.post("/dev/bootstrap", params={"x_proxy_token": "experiment-token"},
                        json={"tenant_id": f"tenant-{suffix}", "workspace_id": f"other-{suffix}",
                              "chat_id": f"other-chat-{suffix}", "user_open_id": f"other-user-{suffix}", "role": "viewer"})
            other = headers | {"x-workspace-id": f"other-{suffix}", "x-user-id": f"other-user-{suffix}"}
            cross_workspace = client.get(f"/v1/incidents/{ids[0]}", headers=other).status_code
            unauthorized = client.post("/v1/incidents", headers=other | {"x-request-id": "unauthorized"},
                                       json={"draft_id": draft, "confirm": True}).status_code
            output = {"environment": "real HTTP + MySQL 8.4; fixture extraction", "runs": results,
                      "same_id_different_body_status": conflict.status_code,
                      "cross_workspace_read_status": cross_workspace,
                      "viewer_review_status": unauthorized}
            (ROOT / "eval/reports/mysql_consistency.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(output, ensure_ascii=False))
    finally:
        process.terminate()
        process.wait(timeout=5)
        log.close()


if __name__ == "__main__":
    main()
