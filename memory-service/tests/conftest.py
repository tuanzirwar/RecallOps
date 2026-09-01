import os
os.environ["RECALLOPS_DATABASE_URL"] = "sqlite:///./test-recallops.db"
os.environ["RECALLOPS_TRUSTED_PROXY_TOKEN"] = "test-token"

import pytest
from fastapi.testclient import TestClient
from app.database import Base, engine
from app.main import app


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    with TestClient(app) as value:
        yield value


@pytest.fixture
def headers(client):
    client.post("/dev/bootstrap?x_proxy_token=test-token", json={})
    return {"x-proxy-token": "test-token", "x-tenant-id": "tenant-demo", "x-workspace-id": "workspace-demo", "x-user-id": "ou_maintainer"}


@pytest.fixture
def committed(client, headers):
    draft = client.post("/v1/drafts", headers=headers, json={"thread_id": "omt_1", "messages": [{
        "message_id": "om_1", "source_url": "https://example.test/thread/1",
        "content": "故障现象：付款成功后订单状态长时间未更新\n最终根因：order-service 数据库连接池耗尽\n临时方案：max_pool_size 从 50 调整到 200\n长期行动：改造动态连接池\n错误 PAYMENT_5032 影响 payment-service"
    }]}).json()
    return client.post("/v1/incidents", headers=headers | {"x-request-id": "req-1"}, json={"draft_id": draft["draft_id"], "confirm": True}).json()

