import io
import json
from app.config import get_settings
from app.extractor import extract_incident


def test_responses_wire_protocol_extracts_structured_draft(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "extraction_mode", "model")
    monkeypatch.setattr(settings, "model_wire_api", "responses")
    monkeypatch.setattr(settings, "model_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "model_api_key", "test-only")
    monkeypatch.setattr(settings, "model_name", "test-model")
    monkeypatch.setattr("app.quota.acquire", lambda: None)
    incident = {"title": "数据库超时", "symptom": "请求失败", "root_cause": "连接池耗尽",
                "resolution": "扩容", "severity": "P2", "error_codes": [],
                "services": [], "actions": []}
    result = {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(incident)}]}]}
    def fake_urlopen(request, timeout):
        assert request.full_url == "https://example.test/v1/responses"
        return io.BytesIO(json.dumps(result).encode())
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert extract_incident([{"content": "测试材料"}])["root_cause"] == "连接池耗尽"
