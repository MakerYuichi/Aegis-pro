CREATE TABLE IF NOT EXISTS services (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    repo_name VARCHAR(255),
    repo_url VARCHAR(255),
    on_call JSONB DEFAULT '[]'::jsonb,
    runbook_url VARCHAR(255),
    slack_channel VARCHAR(255),
    dependencies JSONB DEFAULT '[]'::jsonb,
    is_critical BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_services_name ON services(name);
CREATE INDEX idx_services_is_critical ON services(is_critical);