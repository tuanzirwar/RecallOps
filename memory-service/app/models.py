from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


def now() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    bound_chat_id: Mapped[str | None] = mapped_column(String(128), unique=True)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    user_open_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="viewer")


class Draft(Base):
    __tablename__ = "incident_drafts"
    __table_args__ = (UniqueConstraint("tenant_id", "workspace_id", "content_hash"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    thread_id: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (Index("ix_incident_scope", "tenant_id", "workspace_id", "status"),)
    origin_draft_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    symptom: Mapped[str] = mapped_column(Text)
    root_cause: Mapped[str] = mapped_column(Text)
    resolution: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16), default="unknown")
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    error_codes: Mapped[list] = mapped_column(JSON, default=list)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    index_status: Mapped[str] = mapped_column(String(32), default="pending")
    created_by: Mapped[str] = mapped_column(String(128))
    confirmed_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Service(Base):
    __tablename__ = "services"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))


class IncidentService(Base):
    __tablename__ = "incident_services"
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), primary_key=True)
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32), primary_key=True)


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("incident_id", "content_hash"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="feishu_message")
    message_id: Mapped[str | None] = mapped_column(String(128))
    thread_id: Mapped[str | None] = mapped_column(String(128))
    source_url: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    owner_open_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="open")


class Revision(Base):
    __tablename__ = "incident_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    field: Mapped[str] = mapped_column(String(64))
    old_value: Mapped[str] = mapped_column(Text)
    new_value: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    changed_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class RequestRecord(Base):
    __tablename__ = "request_records"
    request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    operation: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    response: Mapped[dict] = mapped_column(JSON)


class RetrievalLog(Base):
    __tablename__ = "retrieval_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True)
    requester_open_id: Mapped[str] = mapped_column(String(128))
    query: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(16))
    returned_incident_ids: Mapped[list] = mapped_column(JSON)
    latency_ms: Mapped[int] = mapped_column(Integer)


class ExtractionTask(Base):
    __tablename__ = "extraction_tasks"
    __table_args__ = (UniqueConstraint("tenant_id", "workspace_id", "content_hash"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), index=True)
    created_by: Mapped[str] = mapped_column(String(128))
    thread_id: Mapped[str] = mapped_column(String(128))
    messages: Mapped[list] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    draft_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("extraction_tasks.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
