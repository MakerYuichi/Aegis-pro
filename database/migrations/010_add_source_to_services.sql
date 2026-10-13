-- 010_add_source_to_services.sql
--
-- Distinguish services created by a scan from services created
-- manually or seeded.
--
-- 'manual' is the default. Every existing row becomes 'manual'
-- by virtue of the DEFAULT — PostgreSQL 11+ makes
-- `ADD COLUMN ... NOT NULL DEFAULT <const>` a metadata-only
-- operation, no table rewrite.
--
-- 'scan' is set explicitly by IncidentService.resolve_scan_service
-- when a scan is the first thing to reference a repo. The UI can
-- filter on this; cleanup is one DELETE WHERE source = 'scan'.
--
-- The column is NOT NULL with a concrete default, matching the
-- codebase's existing convention for "absence is a normal value"
-- (e.g. is_critical boolean DEFAULT false, on_call jsonb
-- DEFAULT '[]'::jsonb). It is not nullable.

ALTER TABLE services
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'manual';

-- Index for the admin filter and the cleanup query.
CREATE INDEX IF NOT EXISTS idx_services_source ON services(source);
