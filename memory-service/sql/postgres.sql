CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER TABLE incidents ADD COLUMN IF NOT EXISTS search_vector tsvector GENERATED ALWAYS AS (
  to_tsvector('simple', coalesce(title,'') || ' ' || coalesce(symptom,'') || ' ' || coalesce(root_cause,'') || ' ' || coalesce(resolution,''))
) STORED;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS embedding_vector vector(96);

CREATE INDEX IF NOT EXISTS incidents_search_idx ON incidents USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS incidents_embedding_idx ON incidents USING hnsw (embedding_vector vector_cosine_ops);

-- Retrieval SQL must include tenant_id/workspace_id before ranking. These indexes support that invariant.
CREATE INDEX IF NOT EXISTS incidents_scope_idx ON incidents(tenant_id, workspace_id, status);

-- Draft content deduplication is scoped to the authorized data boundary.
ALTER TABLE incident_drafts DROP CONSTRAINT IF EXISTS incident_drafts_content_hash_key;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'uq_draft_scope_content_hash'
  ) THEN
    ALTER TABLE incident_drafts
      ADD CONSTRAINT uq_draft_scope_content_hash UNIQUE (tenant_id, workspace_id, content_hash);
  END IF;
END
$$;
