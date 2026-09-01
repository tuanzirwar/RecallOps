def test_human_gated_idempotent_workflow(client, headers):
    body = {"thread_id": "omt_1", "messages": [{"message_id": "om_1", "source_url": "https://example.test/1", "content": "故障现象：回调超时\n最终根因：连接池耗尽\n临时方案：扩大连接池"}]}
    one = client.post("/v1/drafts", headers=headers, json=body)
    two = client.post("/v1/drafts", headers=headers, json=body)
    assert one.status_code == 200 and one.json()["draft_id"] == two.json()["draft_id"]
    denied = client.post("/v1/incidents", headers=headers | {"x-request-id": "no-confirm"}, json={"draft_id": one.json()["draft_id"], "confirm": False})
    assert denied.status_code == 400
    first = client.post("/v1/incidents", headers=headers | {"x-request-id": "same"}, json={"draft_id": one.json()["draft_id"], "confirm": True})
    replay = client.post("/v1/incidents", headers=headers | {"x-request-id": "same"}, json={"draft_id": one.json()["draft_id"], "confirm": True})
    assert first.status_code == 201 and replay.status_code == 200 and first.json() == replay.json()


def test_hybrid_search_returns_evidence(client, headers, committed):
    response = client.post("/v1/incidents/search", headers=headers, json={"query": "付款之后订单一直没变化", "mode": "hybrid"})
    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["incident_id"] == committed["incident_id"]
    assert item["sources"][0]["source_url"] == "https://example.test/thread/1"
    exact = client.post("/v1/incidents/search", headers=headers, json={"query": "PAYMENT_5032", "mode": "fts"}).json()
    assert exact["results"][0]["retrieval"]["fts_score"] > 0


def test_revision_and_reindex(client, headers, committed):
    incident_id = committed["incident_id"]
    changed = client.patch(f"/v1/incidents/{incident_id}", headers=headers, json={"field": "root_cause", "new_value": "连接池参数配置不合理", "reason": "正式复盘更新"})
    assert changed.json()["index_status"] == "pending"
    detail = client.get(f"/v1/incidents/{incident_id}", headers=headers).json()
    assert detail["revisions"][0]["old_value"] == "order-service 数据库连接池耗尽"
    client.post("/dev/bootstrap?x_proxy_token=test-token", json={"user_open_id": "ou_admin", "role": "admin"})
    admin = headers | {"x-user-id": "ou_admin"}
    assert client.post("/v1/jobs/run", headers=admin).json()["completed"] == 1


def test_workspace_isolation(client, headers, committed):
    client.post("/dev/bootstrap?x_proxy_token=test-token", json={"workspace_id": "workspace-other", "chat_id": "oc_other", "user_open_id": "ou_other"})
    other = headers | {"x-workspace-id": "workspace-other", "x-user-id": "ou_other"}
    assert client.post("/v1/incidents/search", headers=other, json={"query": "PAYMENT_5032"}).json()["results"] == []
    assert client.get(f"/v1/incidents/{committed['incident_id']}", headers=other).status_code == 404


def test_untrusted_identity_rejected(client, headers):
    bad = headers | {"x-proxy-token": "wrong"}
    assert client.post("/v1/incidents/search", headers=bad, json={"query": "anything"}).status_code == 401


def test_no_answer_refuses_untrusted_match(client, headers, committed):
    response = client.post("/v1/incidents/search", headers=headers, json={"query": "火星探测器姿态控制异常", "mode": "hybrid"})
    assert response.status_code == 200
    assert response.json()["results"] == []


def test_draft_deduplication_is_scoped_to_workspace(client, headers):
    body = {"thread_id": "omt_shared", "messages": [{"message_id": "om_shared", "source_url": "https://example.test/shared", "content": "故障现象：相同内容"}]}
    first = client.post("/v1/drafts", headers=headers, json=body)
    client.post("/dev/bootstrap?x_proxy_token=test-token", json={"workspace_id": "workspace-other", "chat_id": "oc_other", "user_open_id": "ou_other"})
    other = headers | {"x-workspace-id": "workspace-other", "x-user-id": "ou_other"}
    second = client.post("/v1/drafts", headers=other, json=body)
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["draft_id"] != second.json()["draft_id"]
