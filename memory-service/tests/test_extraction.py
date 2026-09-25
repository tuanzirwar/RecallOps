from sqlalchemy import select
from app.database import SessionLocal
from app.extraction import process_task
from app.models import ExtractionTask, Incident, OutboxEvent, RequestRecord, Revision

BODY = {"thread_id": "thread-async", "messages": [{"message_id": "message-async", "source_url": "https://example.test/async", "content": "故障现象：数据库连接失败\n最终根因：连接池耗尽\n临时方案：提高连接池上限"}]}


def test_async_extraction_review_and_duplicate_delivery(client, headers):
    first = client.post("/v1/extractions", headers=headers, json=BODY)
    second = client.post("/v1/extractions", headers=headers, json=BODY)
    assert first.status_code == 202
    task_id = first.json()["task_id"]
    assert task_id == second.json()["task_id"]
    with SessionLocal() as db:
        assert db.scalar(select(OutboxEvent).where(OutboxEvent.task_id == task_id)).status == "pending"
        assert process_task(db, task_id) == "succeeded"
        assert process_task(db, task_id) == "succeeded"
        assert db.get(ExtractionTask, task_id).attempts == 1
    result = client.get(f"/v1/extractions/{task_id}", headers=headers).json()
    assert result["incident"]["root_cause"] == "连接池耗尽"
    body = {"draft_id": result["draft_id"], "confirm": True, "corrections": {"root_cause": "数据库连接池耗尽"}}
    request_headers = headers | {"x-request-id": "async-review"}
    approved = client.post("/v1/incidents", headers=request_headers, json=body)
    assert approved.status_code == 201
    assert client.post("/v1/incidents", headers=request_headers, json=body).status_code == 200
    assert client.post("/v1/incidents", headers=request_headers, json=body | {"corrections": {"title": "篡改"}}).status_code == 409
    assert client.post("/v1/incidents", headers=headers | {"x-request-id": "other-id"}, json=body).status_code == 409
    with SessionLocal() as db:
        incident = db.get(Incident, approved.json()["incident_id"])
        assert incident.origin_draft_id == result["draft_id"]
        assert len(db.scalars(select(Revision).where(Revision.incident_id == incident.id)).all()) == 1
        assert db.get(RequestRecord, "other-id") is None


def test_extraction_is_workspace_scoped(client, headers):
    task_id = client.post("/v1/extractions", headers=headers, json=BODY).json()["task_id"]
    client.post("/dev/bootstrap?x_proxy_token=test-token", json={"workspace_id": "another", "chat_id": "oc_another", "user_open_id": "ou_another"})
    other = headers | {"x-workspace-id": "another", "x-user-id": "ou_another"}
    assert client.get(f"/v1/extractions/{task_id}", headers=other).status_code == 404
