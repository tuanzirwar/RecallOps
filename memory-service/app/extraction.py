from __future__ import annotations

import urllib.error
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import get_settings
from .extractor import extract_incident
from .models import Draft, ExtractionTask, OutboxEvent
from .service import digest
from .quota import QuotaUnavailable


def submit(db: Session, tenant_id: str, workspace_id: str, user_id: str, thread_id: str, messages: list[dict]) -> ExtractionTask:
    content_hash = digest(thread_id + "\n" + "\n".join(item["content"] for item in messages))
    existing = db.scalar(select(ExtractionTask).where(
        ExtractionTask.tenant_id == tenant_id,
        ExtractionTask.workspace_id == workspace_id,
        ExtractionTask.content_hash == content_hash,
    ))
    if existing:
        return existing
    task = ExtractionTask(
        id=f"task_{uuid.uuid4().hex}", tenant_id=tenant_id, workspace_id=workspace_id,
        created_by=user_id, thread_id=thread_id, messages=messages, content_hash=content_hash,
        status="queued", attempts=0,
    )
    db.add(task)
    db.add(OutboxEvent(id=f"evt_{uuid.uuid4().hex}", task_id=task.id, status="pending"))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        task = db.scalar(select(ExtractionTask).where(
            ExtractionTask.tenant_id == tenant_id,
            ExtractionTask.workspace_id == workspace_id,
            ExtractionTask.content_hash == content_hash,
        ))
        if task is None:
            raise
    return task


def process_task(db: Session, task_id: str) -> str:
    """结果与任务终态在同一事务提交，消息在返回后才 ACK。"""
    task = db.scalar(select(ExtractionTask).where(ExtractionTask.id == task_id).with_for_update())
    if task is None:
        return "missing"
    if task.status in {"succeeded", "failed"}:
        return task.status
    task.attempts += 1
    try:
        incident = extract_incident(task.messages)
        draft = db.scalar(select(Draft).where(
            Draft.tenant_id == task.tenant_id,
            Draft.workspace_id == task.workspace_id,
            Draft.content_hash == task.content_hash,
        ))
        if draft is None:
            draft = Draft(
                id=f"draft_{uuid.uuid4().hex[:12]}", tenant_id=task.tenant_id,
                workspace_id=task.workspace_id, thread_id=task.thread_id,
                payload={"incident": incident, "messages": task.messages},
                content_hash=task.content_hash, status="pending",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=get_settings().draft_ttl_hours),
                created_by=task.created_by,
            )
            db.add(draft)
        task.draft_id = draft.id
        task.status = "succeeded"
        task.last_error = None
        db.commit()
        return task.status
    except Exception as exc:
        db.rollback()
        task = db.get(ExtractionTask, task_id)
        retryable = isinstance(exc, QuotaUnavailable) or isinstance(exc, TimeoutError)
        if isinstance(exc, urllib.error.HTTPError):
            retryable = exc.code == 429 or exc.code >= 500
        elif isinstance(exc, urllib.error.URLError):
            retryable = True
        if not isinstance(exc, QuotaUnavailable):
            task.attempts += 1
        task.status = "queued" if retryable and task.attempts < 3 else "failed"
        task.last_error = str(exc)[:1000]
        db.commit()
        return task.status


def retry_task(db: Session, task: ExtractionTask) -> ExtractionTask:
    if task.status != "failed":
        raise ValueError("only failed tasks can be retried")
    task.status = "queued"
    task.attempts = 0
    task.last_error = None
    db.add(OutboxEvent(id=f"evt_{uuid.uuid4().hex}", task_id=task.id, status="pending"))
    db.commit()
    return task
