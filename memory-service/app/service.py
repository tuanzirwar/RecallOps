from __future__ import annotations
import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Action, Draft, Incident, IncidentService, Job, Revision, Service, Source
from .retrieval import embed, incident_text
from .postgres import store_embedding


class DraftAlreadyCommitted(ValueError):
    pass


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def extract(messages: list[dict]) -> dict:
    text = "\n".join(item["content"] for item in messages)
    labels = {
        "title": ["故障现象", "标题"], "symptom": ["故障现象", "现象"],
        "root_cause": ["最终根因", "根因"], "resolution": ["临时方案", "处理方案", "解决方案"],
        "severity": ["严重等级", "级别"],
    }
    result = {}
    for key, variants in labels.items():
        found = None
        for label in variants:
            match = re.search(rf"(?:^|\n)\s*{label}[：:]\s*([^\n]+)", text)
            if match:
                found = match.group(1).strip()
                break
        result[key] = found or (text.splitlines()[0][:200] if key in {"title", "symptom"} else "待确认")
    result["error_codes"] = sorted(set(re.findall(r"\b[A-Z][A-Z0-9]+(?:[_-][A-Z0-9]+)+\b", text)))
    result["services"] = [{"name": x, "role": "affected"} for x in sorted(set(re.findall(r"\b[a-z][a-z0-9-]+-service\b", text)))]
    result["actions"] = []
    for label in ("长期行动", "行动项"):
        match = re.search(rf"(?:^|\n)\s*{label}[：:]\s*([^\n]+)", text)
        if match:
            result["actions"].append({"description": match.group(1).strip(), "status": "open"})
    return result


def create_draft(db: Session, tenant_id: str, workspace_id: str, user_id: str, thread_id: str, messages: list[dict], ttl: int) -> Draft:
    content_hash = digest(thread_id + "\n" + "\n".join(x["content"] for x in messages))
    existing = db.scalar(select(Draft).where(
        Draft.tenant_id == tenant_id,
        Draft.workspace_id == workspace_id,
        Draft.content_hash == content_hash,
    ))
    if existing:
        return existing
    row = Draft(id=f"draft_{uuid.uuid4().hex[:12]}", tenant_id=tenant_id, workspace_id=workspace_id, thread_id=thread_id,
                payload={"incident": extract(messages), "messages": messages}, content_hash=content_hash,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl), created_by=user_id)
    db.add(row); db.commit(); db.refresh(row)
    return row


def commit_draft(db: Session, draft: Draft, corrections: dict, user_id: str) -> Incident:
    if draft.status == "committed":
        raise DraftAlreadyCommitted("draft already committed")
    allowed = {"title", "symptom", "root_cause", "resolution", "severity", "error_codes", "services", "actions"}
    if set(corrections) - allowed:
        raise ValueError("unsupported correction field")
    data = dict(draft.payload["incident"]); data.update(corrections)
    incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
    row = Incident(id=incident_id, origin_draft_id=draft.id, tenant_id=draft.tenant_id, workspace_id=draft.workspace_id,
                   title=str(data["title"]), symptom=str(data["symptom"]), root_cause=str(data["root_cause"]),
                   resolution=str(data["resolution"]), severity=str(data.get("severity", "unknown")),
                   error_codes=list(data.get("error_codes", [])), created_by=draft.created_by, confirmed_by=user_id)
    db.add(row); db.flush()
    for field, value in corrections.items():
        original = draft.payload["incident"].get(field)
        if original != value:
            db.add(Revision(incident_id=row.id, field=field,
                            old_value=str(original), new_value=str(value),
                            reason="审核修订", changed_by=user_id))
    names = []
    for item in data.get("services", []):
        service = db.scalar(select(Service).where(Service.tenant_id == draft.tenant_id, Service.name == item["name"]))
        if not service:
            service = Service(tenant_id=draft.tenant_id, name=item["name"]); db.add(service); db.flush()
        names.append(service.name); db.add(IncidentService(incident_id=row.id, service_id=service.id, role=item.get("role", "affected")))
    for item in draft.payload["messages"]:
        db.add(Source(incident_id=row.id, message_id=item["message_id"], thread_id=draft.thread_id,
                      source_url=item["source_url"], content=item["content"], content_hash=digest(item["message_id"] + item["content"])))
    for item in data.get("actions", []):
        db.add(Action(incident_id=row.id, description=item["description"], owner_open_id=item.get("owner_open_id"), status=item.get("status", "open")))
    row.embedding = embed(incident_text(row, names)); row.embedding_model = "local-hashing-96"; row.embedding_version = "1"; row.index_status = "ready"
    store_embedding(db, row.id, row.embedding)
    db.add(Job(job_type="embedding", payload={"incident_id": row.id}, status="completed", attempts=1))
    payload = dict(draft.payload); payload["incident_id"] = row.id; draft.payload = payload; draft.status = "committed"
    db.flush(); db.refresh(row)
    return row
