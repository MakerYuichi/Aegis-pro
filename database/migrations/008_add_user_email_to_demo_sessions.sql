-- Add user_email and onboarding_clicked_at to demo_sessions.
--
-- Purpose (Phase 10 — Demo-to-Dashboard Continuity):
--   * user_email links a demo session to a signed-in user, so the
--     dashboard can show "You tried github.com/stripe/charge-service".
--   * onboarding_clicked_at records intent when the user clicks
--     "Connect it now" — a lead signal, and the funnel metric that
--     Phase 11 (real onboarding) will build on.
--
-- Both columns are nullable. Existing rows keep NULL user_email and
-- are simply invisible to /api/v1/me/demo-sessions. The admin panel
-- (src/api/admin.py) is unaffected — it does not filter on user_email.
--
-- Runs on fresh Postgres volume at /docker-entrypoint-initdb.d.
-- Idempotent: safe to rerun.

ALTER TABLE demo_sessions
    ADD COLUMN IF NOT EXISTS user_email TEXT NULL,
    ADD COLUMN IF NOT EXISTS onboarding_clicked_at TIMESTAMP NULL;

CREATE INDEX IF NOT EXISTS idx_demo_sessions_user_email
    ON demo_sessions(user_email, created_at DESC)
    WHERE user_email IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_demo_sessions_onboarding_clicked
    ON demo_sessions(onboarding_clicked_at)
    WHERE onboarding_clicked_at IS NOT NULL;

COMMENT ON COLUMN demo_sessions.user_email IS
    'Lowercased email from the authenticated user''s JWT. NULL for anonymous demo sessions. See Phase 10.';
COMMENT ON COLUMN demo_sessions.onboarding_clicked_at IS
    'Timestamp when the user clicked "Connect it now" on the demo session card. Funnel signal for Phase 11.';
