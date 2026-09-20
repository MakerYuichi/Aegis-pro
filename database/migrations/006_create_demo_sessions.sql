-- Demo session tracking.
--
-- Written by POST /api/v1/demo/generate on every call — success or failure.
-- Read by the admin panel (issue #40) to answer:
--   * Which orgs are pasting URLs? (lead signal)
--   * Which inputs fail to parse, and why? (product signal)
--   * Did this specific session convert to a signup? (funnel signal)
--
-- Runs on fresh Postgres volume at /docker-entrypoint-initdb.d.
-- Retention: rows older than 30 days are purged on write.

CREATE TABLE IF NOT EXISTS demo_sessions (
    id              SERIAL PRIMARY KEY,
    session_id      VARCHAR(64) NOT NULL,
    raw_input       TEXT,
    parsed_org      VARCHAR(255),
    parsed_repo     VARCHAR(255),
    language_inferred VARCHAR(32),
    parse_ok        BOOLEAN NOT NULL,
    error_reason    VARCHAR(64),
    incident_payload JSONB,
    incident_id     VARCHAR(64),
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_demo_sessions_session_id ON demo_sessions(session_id);
CREATE INDEX idx_demo_sessions_created_at ON demo_sessions(created_at DESC);
CREATE INDEX idx_demo_sessions_parsed_org ON demo_sessions(parsed_org);
CREATE INDEX idx_demo_sessions_parse_ok ON demo_sessions(parse_ok);

COMMENT ON TABLE demo_sessions IS 'Log of /demo/generate calls for lead analytics. Never contains secrets.';
COMMENT ON COLUMN demo_sessions.incident_payload IS 'The full generated incident, so admin replay works even after generator templates change.';
