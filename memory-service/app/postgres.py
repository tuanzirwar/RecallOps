import time
from pathlib import Path

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session


def enabled(bind) -> bool:
    return bind.dialect.name == "postgresql"


def migrate(engine: Engine) -> None:
    if not enabled(engine):
        return
    sql = (Path(__file__).resolve().parents[1] / "sql" / "postgres.sql").read_text(encoding="utf-8")
    with engine.begin() as connection:
        connection.exec_driver_sql(sql)


def store_embedding(db: Session, incident_id: str, vector: list[float]) -> None:
    if not enabled(db.get_bind()):
        return
    literal = "[" + ",".join(f"{value:.9f}" for value in vector) + "]"
    db.execute(text("UPDATE incidents SET embedding_vector = CAST(:value AS vector) WHERE id = :id"), {"value": literal, "id": incident_id})


def candidate_ids(
    db: Session,
    tenant_id: str,
    workspace_id: str,
    query: str,
    vector: list[float],
    mode: str,
    limit: int = 50,
    timings: dict[str, float] | None = None,
) -> list[str] | None:
    if not enabled(db.get_bind()):
        return None
    common = {"tenant": tenant_id, "workspace": workspace_id, "query": query, "limit": limit}
    found: list[str] = []
    if mode in {"fts", "hybrid"}:
        started = time.perf_counter()
        statement = text("""
          SELECT id FROM incidents
          WHERE tenant_id=:tenant AND workspace_id=:workspace AND status='active'
            AND (
              search_vector @@ plainto_tsquery('simple', :query)
              OR EXISTS (
                SELECT 1 FROM jsonb_array_elements_text(error_codes::jsonb) code
                WHERE lower(:query) LIKE '%' || lower(code) || '%' OR lower(code) LIKE '%' || lower(:query) || '%'
              )
              OR EXISTS (
                SELECT 1 FROM incident_services rel JOIN services svc ON svc.id=rel.service_id
                WHERE rel.incident_id=incidents.id
                  AND (lower(:query) LIKE '%' || lower(svc.name) || '%' OR lower(svc.name) LIKE '%' || lower(:query) || '%')
              )
            )
          ORDER BY ts_rank_cd(search_vector, plainto_tsquery('simple', :query)) DESC, id LIMIT :limit
        """)
        found.extend(db.execute(statement, common).scalars().all())
        if timings is not None:
            timings["fts"] = timings.get("fts", 0.0) + (
                time.perf_counter() - started
            ) * 1000
    if mode in {"vector", "hybrid"}:
        started = time.perf_counter()
        literal = "[" + ",".join(f"{value:.9f}" for value in vector) + "]"
        statement = text("""
          SELECT id FROM incidents
          WHERE tenant_id=:tenant AND workspace_id=:workspace AND status='active' AND embedding_vector IS NOT NULL
          ORDER BY embedding_vector <=> CAST(:vector AS vector) LIMIT :limit
        """)
        found.extend(db.execute(statement, common | {"vector": literal}).scalars().all())
        if timings is not None:
            timings["vector_search"] = timings.get("vector_search", 0.0) + (
                time.perf_counter() - started
            ) * 1000
    return list(dict.fromkeys(found))
