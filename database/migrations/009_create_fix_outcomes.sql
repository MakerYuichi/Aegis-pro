-- Fix outcomes for the Curator stage.
--
-- Every human approve/reject on an auto-generated fix writes one row
-- here. The Verifier's result is captured alongside, so the Curator
-- can retrieve past outcomes that were both approved AND verified
-- (strong positive signal) or rejected (strong negative signal).
--
-- Embedding text mirrors incidents.embedding: title + description +
-- stack_trace for incidents, root_cause + suggested_fix + stack
-- context for outcomes. Same encoder (all-MiniLM-L6-v2, 384 dims),
-- so similarity comparisons between a live incident and a stored
-- outcome are meaningfully comparable.

CREATE EXTENSION IF NOT EXISTS vector;

DROP TABLE IF EXISTS fix_outcomes CASCADE;

CREATE TABLE IF NOT EXISTS fix_outcomes (
    id SERIAL PRIMARY KEY,

    -- FK to the business key, not the surrogate. incident_id is
    -- VARCHAR(50) UNIQUE NOT NULL on incidents; the ORM and every
    -- query in the codebase uses this column.
    incident_id VARCHAR(50) NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,

    -- Denormalized at write time. See the migration comment in the
    -- PR description: this is a historical record of what was true
    -- when the fix happened, not a live view of services.repo_name.
    service_name VARCHAR(255) NOT NULL,
    repo_name VARCHAR(255),

    -- The fix that was proposed, verbatim.
    fix_diff TEXT,

    -- Verification result at the time of the decision.
    verification_passed BOOLEAN,
    verification_reason VARCHAR(64),

    -- The human decision. Both columns are NOT NULL because a row is
    -- only written once a human has decided. A fix that was generated
    -- and verified but never approved or rejected is not an outcome.
    human_decision VARCHAR(16) NOT NULL CHECK (human_decision IN ('approved', 'rejected')),
    human_reason TEXT,

    -- Denormalized from the incident at write time, for embedding
    -- text construction. Same shape as the incident's own embedding
    -- input so the two vectors are comparable.
    root_cause TEXT,
    suggested_fix TEXT,
    stack_context TEXT,

    -- 384-dim vector from sentence-transformers for similarity search.
    -- Same encoder and dimensions as incidents.embedding.
    embedding vector(384),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_fix_outcomes_incident_id ON fix_outcomes(incident_id);
CREATE INDEX idx_fix_outcomes_service_name_created_at ON fix_outcomes(service_name, created_at DESC);
CREATE INDEX idx_fix_outcomes_repo_name_created_at ON fix_outcomes(repo_name, created_at DESC);
CREATE INDEX idx_fix_outcomes_embedding ON fix_outcomes USING ivfflat (embedding vector_cosine_ops);

COMMENT ON TABLE fix_outcomes IS 'Human approve/reject outcomes for auto-generated fixes, used as few-shot examples by the Curator stage';
COMMENT ON COLUMN fix_outcomes.embedding IS '384-dim vector from sentence-transformers, same encoder as incidents.embedding';
COMMENT ON COLUMN fix_outcomes.human_decision IS 'approved | rejected. Rows are only written after a human decision.';
