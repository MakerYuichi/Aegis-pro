-- Alert history table.
--
-- Historically created programmatically by init_db() at app startup.
-- The test suite uses this table directly and doesn't run the app's
-- lifespan, so the table must exist from migrations.

CREATE TABLE IF NOT EXISTS alert_history (
    id SERIAL PRIMARY KEY,
    engineer_name VARCHAR(255),
    service_name VARCHAR(255),
    message TEXT,
    status VARCHAR(50) DEFAULT 'sent',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alert_history_created_at
    ON alert_history(created_at DESC);
