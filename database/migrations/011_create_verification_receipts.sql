-- 011_create_verification_receipts.sql
--
-- Durable record of every verification the pipeline performs.
--
-- The receipt is the auditable artifact: it names the commit, the
-- diff, the image digest, the full resolved dependency tree, and
-- the test outcome. Six months later, a reviewer can look up
-- receipt_id and see exactly what environment a "verified" claim
-- was made in.
--
-- Not a gate. A record. The only condition the pipeline blocks on
-- is the case of the same package filename appearing with a
-- different hash from the index between two runs — the case where
-- the cache's content-addressable invariant is violated. Everything
-- else is stored and reported.
--
-- The `packages` column is JSONB: one row per receipt, one JSON
-- document per receipt. A GIN index is created for the future case
-- of cross-repo queries ("which repos ran torch 2.14.0+cpu?"), which
-- has no consumer yet but costs nothing to enable.

CREATE TABLE IF NOT EXISTS verification_receipts (
    receipt_id       UUID PRIMARY KEY,
    incident_id      TEXT REFERENCES incidents(incident_id) ON DELETE SET NULL,
    commit_sha       TEXT,
    diff_hash        TEXT,
    image_digest     TEXT,
    manifest_hash    TEXT NOT NULL,
    python_version   TEXT NOT NULL,
    platform_tag     TEXT NOT NULL,
    test_command     TEXT,
    exit_code        INTEGER,
    test_counts      JSONB,
    packages         JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_receipts_incident
    ON verification_receipts(incident_id);

CREATE INDEX IF NOT EXISTS idx_receipts_manifest_hash
    ON verification_receipts(manifest_hash);

CREATE INDEX IF NOT EXISTS idx_receipts_created_at
    ON verification_receipts(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_receipts_packages
    ON verification_receipts USING gin (packages);

COMMENT ON TABLE verification_receipts IS
    'Per-verification auditable record. Written by the orchestrator '
    'after the verifier finishes; read by admin tooling and the '
    'Curator. See src/agents/prefetch/ for the prefetch phase and '
    'docs/ARCHITECTURE.md for the trust model.';

COMMENT ON COLUMN verification_receipts.packages IS
    'Full resolved dependency tree as JSONB. Each element: '
    '{name, base_version, local_variant, extras, environment_marker, '
    'hashes, source_index, filename, dependencies}.';
