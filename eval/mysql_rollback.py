from __future__ import annotations
import concurrent.futures
import json
import os
import sys
import uuid
from pathlib import Path
import httpx
from sqlalchemy import select, func

ROOT = Path(__file__).resolve().parents[1]
DB = "mysql+pymysql://recallops:recallops@127.0.0.1:3306/recallops?charset=utf8mb4"
os.environ["RECALLOPS_DATABASE_URL"] = DB
sys.path.insert(0, str(ROOT / "memory-service"))
from app.database import SessionLocal
from app.models import Draft, Incident, Source, Revision, Job
import app.service as service

suffix = uuid.uuid4().hex[:8]
with SessionLocal() as db:
    from app.models import Tenant, Workspace, WorkspaceMember
    db.add(Tenant(id=f"rollback-{suffix}", name="Rollback experiment"))
    db.flush()
    db.add(Workspace(id=f"rollback-ws-{suffix}", tenant_id=f"rollback-{suffix}", name="Rollback workspace"))
    db.flush()
    db.add(WorkspaceMember(workspace_id=f"rollback-ws-{suffix}", user_open_id=f"rollback-user-{suffix}", role="maintainer"))
    db.commit()
    draft = service.create_draft(db, f"rollback-{suffix}", f"rollback-ws-{suffix}", f"rollback-user-{suffix}",
                                 f"rollback-thread-{suffix}", [{"message_id": f"rollback-msg-{suffix}",
                                 "source_url": f"https://example.test/rollback/{suffix}",
                                 "content": "故障现象：回滚检查\n最终根因：连接池耗尽\n临时方案：扩容"}], 24)
    draft_id = draft.id
    original = service.store_embedding
    def fail_after_flush(db, incident_id, vector):
        db.flush()
        raise RuntimeError("injected after partial SQL flush")
    service.store_embedding = fail_after_flush
    try:
        try:
            service.commit_draft(db, draft, {"root_cause": "修订后的根因"}, f"rollback-user-{suffix}")
        except RuntimeError:
            db.rollback()
        else:
            raise AssertionError("fault not triggered")
    finally:
        service.store_embedding = original
    db.expire_all()
    result = {"draft_status": db.get(Draft, draft_id).status,
              "incident_count": db.scalar(select(func.count()).select_from(Incident).where(Incident.origin_draft_id == draft_id)),
              "source_count": db.scalar(select(func.count()).select_from(Source).where(Source.message_id == f"rollback-msg-{suffix}")),
              "revision_count": db.scalar(select(func.count()).select_from(Revision).where(Revision.changed_by == f"rollback-user-{suffix}"))}

with httpx.Client(base_url="http://127.0.0.1:18000", timeout=20) as client:
    client.post("/dev/bootstrap", params={"x_proxy_token": "dev-proxy-token"}, json={
        "tenant_id": f"different-{suffix}", "workspace_id": f"different-ws-{suffix}",
        "chat_id": f"different-chat-{suffix}", "user_open_id": f"different-user-{suffix}",
        "role": "maintainer"}).raise_for_status()
    headers = {"x-proxy-token": "dev-proxy-token", "x-tenant-id": f"different-{suffix}",
               "x-workspace-id": f"different-ws-{suffix}", "x-user-id": f"different-user-{suffix}"}
    draft = client.post("/v1/drafts", headers=headers, json={"thread_id": f"different-{suffix}",
        "messages": [{"message_id": f"different-msg-{suffix}",
                      "source_url": f"https://example.test/different/{suffix}",
                      "content": "故障现象：并发审核\n最终根因：连接池耗尽\n临时方案：扩容"}]}).json()["draft_id"]
    def send(i):
        return client.post("/v1/incidents", headers=headers | {"x-request-id": f"different-{suffix}-{i}"},
                           json={"draft_id": draft, "confirm": True}).status_code
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        statuses = list(pool.map(send, range(10)))
    with SessionLocal() as db:
        one_incident = db.scalar(select(func.count()).select_from(Incident).where(Incident.origin_draft_id == draft))

output = {"environment": "MySQL 8.4; transaction fault after SQL flush and real HTTP concurrent review",
          "rollback": result,
          "different_request_ids_same_draft": {"requests": 10, "created": statuses.count(201),
                                               "conflicts": statuses.count(409),
                                               "incident_count": one_incident}}
(ROOT / "eval/reports/mysql_rollback.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(output, ensure_ascii=False))
