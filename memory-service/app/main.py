from __future__ import annotations

import hashlib
import json
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import Identity, identity, require
from .config import get_settings
from .database import Base, engine, get_db
from .models import (
    Action,
    Draft,
    ExtractionTask,
    Incident,
    IncidentService,
    Job,
    RequestRecord,
    RetrievalLog,
    Revision,
    Service,
    Source,
    Tenant,
    Workspace,
    WorkspaceMember,
)
from .postgres import candidate_ids, store_embedding
from .postgres import migrate as migrate_postgres
from .retrieval import embed as query_embedding
from .retrieval import rank, trusted_match
from .retrieval import tokens as query_tokens
from .schemas import (
    BootstrapRequest,
    CommitRequest,
    CorrectionRequest,
    DraftCreate,
    SearchRequest,
)
from .service import DraftAlreadyCommitted, commit_draft, create_draft
from .extraction import retry_task, submit
from .trace import TraceEvent, recorder


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    migrate_postgres(engine)
    yield


app = FastAPI(title="RecallOps Memory Service", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/dev/bootstrap")
def bootstrap(
    body: BootstrapRequest, x_proxy_token: str, db: Session = Depends(get_db)
) -> dict:
    if x_proxy_token != get_settings().trusted_proxy_token:
        raise HTTPException(401, "untrusted caller")
    if not db.get(Tenant, body.tenant_id):
        db.add(Tenant(id=body.tenant_id, name=body.tenant_name))
    if not db.get(Workspace, body.workspace_id):
        db.add(
            Workspace(
                id=body.workspace_id,
                tenant_id=body.tenant_id,
                name=body.workspace_name,
                bound_chat_id=body.chat_id,
            )
        )
    member = db.get(WorkspaceMember, (body.workspace_id, body.user_open_id))
    if member:
        member.role = body.role
    else:
        db.add(
            WorkspaceMember(
                workspace_id=body.workspace_id,
                user_open_id=body.user_open_id,
                role=body.role,
            )
        )
    db.commit()
    return body.model_dump()


@app.post("/v1/drafts")
def draft(
    body: DraftCreate,
    subject: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> dict:
    require(subject, "member")
    row = create_draft(
        db,
        subject.tenant_id,
        subject.workspace_id,
        subject.user_id,
        body.thread_id,
        [x.model_dump() for x in body.messages],
        get_settings().draft_ttl_hours,
    )
    return {
        "draft_id": row.id,
        "status": row.status,
        "incident": row.payload["incident"],
        "expires_at": row.expires_at,
    }


@app.post("/v1/extractions", status_code=202)
def submit_extraction(
    body: DraftCreate,
    subject: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> dict:
    require(subject, "member")
    task = submit(db, subject.tenant_id, subject.workspace_id, subject.user_id,
                  body.thread_id, [item.model_dump() for item in body.messages])
    return {"task_id": task.id, "status": task.status, "draft_id": task.draft_id}


@app.get("/v1/extractions/{task_id}")
def get_extraction(
    task_id: str,
    subject: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> dict:
    task = db.get(ExtractionTask, task_id)
    if not task or task.tenant_id != subject.tenant_id or task.workspace_id != subject.workspace_id:
        raise HTTPException(404, "extraction not found")
    result = {"task_id": task.id, "status": task.status, "draft_id": task.draft_id,
              "attempts": task.attempts, "last_error": task.last_error}
    if task.draft_id:
        draft = db.get(Draft, task.draft_id)
        result["incident"] = draft.payload["incident"]
    return result


@app.post("/v1/extractions/{task_id}/retry", status_code=202)
def retry_extraction(
    task_id: str,
    subject: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> dict:
    require(subject, "member")
    task = db.scalar(select(ExtractionTask).where(ExtractionTask.id == task_id).with_for_update())
    if not task or task.tenant_id != subject.tenant_id or task.workspace_id != subject.workspace_id:
        raise HTTPException(404, "extraction not found")
    try:
        retry_task(db, task)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"task_id": task.id, "status": task.status}


@app.post("/v1/incidents", status_code=201)
def commit(
    body: CommitRequest,
    response: Response,
    x_request_id: str = Header(...),
    subject: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> dict:
    require(subject, "maintainer")
    if not body.confirm:
        raise HTTPException(400, "explicit confirmation is required")
    fingerprint = hashlib.sha256(json.dumps({
        "tenant": subject.tenant_id, "workspace": subject.workspace_id,
        "user": subject.user_id, "draft": body.draft_id,
        "corrections": body.corrections, "confirm": body.confirm,
    }, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    saved = _idempotency_result(db, x_request_id, fingerprint)
    if saved is not None:
        response.status_code = 200
        return saved
    try:
        db.add(RequestRecord(request_id=x_request_id, operation="incident_commit",
                             fingerprint=fingerprint, response={"_state": "processing"}))
        db.flush()
    except IntegrityError:
        db.rollback()
        saved = _wait_idempotency_result(db, x_request_id, fingerprint)
        response.status_code = 200
        return saved
    try:
        draft_row = db.scalar(select(Draft).where(Draft.id == body.draft_id).with_for_update())
        if not draft_row or draft_row.workspace_id != subject.workspace_id or draft_row.tenant_id != subject.tenant_id:
            raise HTTPException(404, "draft not found")
        row = commit_draft(db, draft_row, body.corrections, subject.user_id)
        result = {"incident_id": row.id, "status": row.status,
                  "index_status": row.index_status}
        record = db.get(RequestRecord, x_request_id)
        record.response = result
        db.commit()
        return result
    except DraftAlreadyCommitted as exc:
        db.rollback()
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(400, str(exc)) from exc
    except Exception:
        db.rollback()
        raise


def _idempotency_result(db: Session, request_id: str, fingerprint: str) -> dict | None:
    saved = db.get(RequestRecord, request_id)
    if saved is None:
        return None
    if saved.operation != "incident_commit" or saved.fingerprint != fingerprint:
        raise HTTPException(409, "request id reused with different content or identity")
    if saved.response.get("_state") == "processing":
        return None
    return saved.response


def _wait_idempotency_result(
    db: Session, request_id: str, fingerprint: str, timeout_seconds: float = 10.0
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        db.expire_all()
        saved = _idempotency_result(db, request_id, fingerprint)
        if saved is not None:
            return saved
        time.sleep(0.01)
    raise HTTPException(409, "request is still processing")


def details(db: Session, row: Incident) -> dict:
    services = db.execute(
        select(Service.name, IncidentService.role)
        .join(IncidentService, Service.id == IncidentService.service_id)
        .where(IncidentService.incident_id == row.id)
    ).all()
    sources = db.scalars(select(Source).where(Source.incident_id == row.id)).all()
    actions = db.scalars(select(Action).where(Action.incident_id == row.id)).all()
    revisions = db.scalars(
        select(Revision)
        .where(Revision.incident_id == row.id)
        .order_by(Revision.id.desc())
    ).all()
    return {
        "incident_id": row.id,
        "title": row.title,
        "symptom": row.symptom,
        "root_cause": row.root_cause,
        "resolution": row.resolution,
        "severity": row.severity,
        "status": row.status,
        "error_codes": row.error_codes,
        "services": [{"name": n, "role": r} for n, r in services],
        "sources": [
            {
                "message_id": x.message_id,
                "source_url": x.source_url,
                "content": x.content,
            }
            for x in sources
        ],
        "actions": [
            {"description": x.description, "status": x.status} for x in actions
        ],
        "revisions": [
            {
                "field": x.field,
                "old_value": x.old_value,
                "new_value": x.new_value,
                "reason": x.reason,
                "changed_by": x.changed_by,
            }
            for x in revisions
        ],
    }


@app.get("/v1/incidents/{incident_id}")
def get_incident(
    incident_id: str,
    subject: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(Incident, incident_id)
    if (
        not row
        or row.workspace_id != subject.workspace_id
        or row.tenant_id != subject.tenant_id
    ):
        raise HTTPException(404, "incident not found")
    return details(db, row)


@app.post("/v1/incidents/search")
def search(
    body: SearchRequest,
    subject: Identity = Depends(identity),
    db: Session = Depends(get_db),
    x_request_id: str | None = Header(None),
) -> dict:
    started = time.perf_counter()
    trace = TraceEvent(
        "retrieval",
        request_id=x_request_id or TraceEvent("retrieval").request_id,
        session_id=subject.workspace_id,
        request_bytes=len(body.model_dump_json().encode("utf-8")),
        metadata={"mode": body.mode, "top_k": body.top_k},
    )
    stages = trace.metadata["stage_latencies_ms"] = {}
    stage = time.perf_counter()
    query_tokens(body.query)
    stages["query_parse"] = round((time.perf_counter() - stage) * 1000, 3)
    stage = time.perf_counter()
    vector = query_embedding(body.query)
    stages["embedding"] = round((time.perf_counter() - stage) * 1000, 3)
    candidates = candidate_ids(
        db,
        subject.tenant_id,
        subject.workspace_id,
        body.query,
        vector,
        body.mode,
        timings=stages,
    )
    statement = select(Incident).where(
        Incident.tenant_id == subject.tenant_id,
        Incident.workspace_id == subject.workspace_id,
        Incident.status == "active",
    )
    if candidates is not None:
        statement = statement.where(Incident.id.in_(candidates))
    incidents = db.scalars(statement).all()
    service_names_by_incident: dict[str, list[str]] = {}
    if incidents:
        if get_settings().service_load_mode == "n_plus_one":
            # 仅用于复现实验基线，正式配置应使用 batch。
            for row in incidents:
                service_names_by_incident[row.id] = list(db.scalars(
                    select(Service.name).join(IncidentService,
                    Service.id == IncidentService.service_id)
                    .where(IncidentService.incident_id == row.id)
                ).all())
        else:
            # 批量加载服务关联，避免每条候选故障再执行一次 SQL。
            services = db.execute(
                select(IncidentService.incident_id, Service.name)
                .join(Service, Service.id == IncidentService.service_id)
                .where(IncidentService.incident_id.in_([row.id for row in incidents]))
            ).all()
            for incident_id, name in services:
                service_names_by_incident.setdefault(incident_id, []).append(name)
    rows = []
    for row in incidents:
        names = service_names_by_incident.get(row.id, [])
        if body.service_names and not set(body.service_names).intersection(names):
            continue
        if body.error_codes and not set(body.error_codes).intersection(
            row.error_codes or []
        ):
            continue
        rows.append((row, names))
    ranked_all = rank(
        rows,
        body.query,
        body.mode,
        get_settings().rrf_k,
        query_vector=vector,
        timings=stages,
    )
    for name in ("fts", "vector_search", "rrf"):
        stages[name] = round(stages.get(name, 0.0), 3)
    stage = time.perf_counter()
    ranked = [item for item in ranked_all if trusted_match(item[1], body.mode)][
        : body.top_k
    ]
    stages["reranker"] = round((time.perf_counter() - stage) * 1000, 3)
    results = []
    for row, scores in ranked:
        item = details(db, row)
        item["retrieval"] = scores
        results.append(item)
    elapsed = int((time.perf_counter() - started) * 1000)
    db.add(
        RetrievalLog(
            tenant_id=subject.tenant_id,
            workspace_id=subject.workspace_id,
            requester_open_id=subject.user_id,
            query=body.query,
            mode=body.mode,
            returned_incident_ids=[x[0].id for x in ranked],
            latency_ms=elapsed,
        )
    )
    db.commit()
    response = {
        "query": body.query,
        "mode": body.mode,
        "results": results,
        "latency_ms": elapsed,
        "answer_policy": "Only cite returned evidence; say no trusted case was found when results is empty.",
    }
    encoded = json.dumps(response, ensure_ascii=False, default=str).encode("utf-8")
    trace.response_bytes = trace.tool_output_bytes = len(encoded)
    trace.tool_output_tokens = (len(encoded) + 3) // 4
    trace.tool_latency_ms = elapsed
    trace.metadata["result_count"] = len(results)
    recorder.record(trace)
    return response


@app.patch("/v1/incidents/{incident_id}")
def correct(
    incident_id: str,
    body: CorrectionRequest,
    subject: Identity = Depends(identity),
    db: Session = Depends(get_db),
) -> dict:
    require(subject, "maintainer")
    row = db.get(Incident, incident_id)
    if not row or row.workspace_id != subject.workspace_id:
        raise HTTPException(404, "incident not found")
    old = str(getattr(row, body.field))
    setattr(row, body.field, body.new_value)
    row.index_status = "pending"
    db.add(
        Revision(
            incident_id=row.id,
            field=body.field,
            old_value=old,
            new_value=body.new_value,
            reason=body.reason,
            changed_by=subject.user_id,
        )
    )
    db.add(Job(job_type="embedding", payload={"incident_id": row.id}, status="pending"))
    db.commit()
    return {
        "incident_id": row.id,
        "field": body.field,
        "old_value": old,
        "new_value": body.new_value,
        "index_status": row.index_status,
    }


@app.post("/v1/jobs/run")
def run_jobs(
    subject: Identity = Depends(identity), db: Session = Depends(get_db)
) -> dict:
    require(subject, "admin")
    pending = db.scalars(select(Job).where(Job.status == "pending")).all()
    completed = 0
    from .retrieval import embed, incident_text

    for job in pending:
        job.attempts += 1
        try:
            row = db.get(Incident, job.payload["incident_id"])
            if not row:
                raise ValueError("incident missing")
            names = list(
                db.scalars(
                    select(Service.name)
                    .join(IncidentService)
                    .where(IncidentService.incident_id == row.id)
                ).all()
            )
            row.embedding = embed(incident_text(row, names))
            store_embedding(db, row.id, row.embedding)
            row.index_status = "ready"
            job.status = "completed"
            job.last_error = None
            completed += 1
        except Exception as exc:
            job.status = "failed" if job.attempts >= 3 else "pending"
            job.last_error = str(exc)
    db.commit()
    return {"processed": len(pending), "completed": completed}
