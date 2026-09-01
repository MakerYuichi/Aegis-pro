CREATE EXTENSION IF NOT EXISTS vector;

-- Create incidents table
CREATE TABLE IF NOT EXISTS incidents (
    id SERIAL PRIMARY KEY,
    incident_id VARCHAR(50) UNIQUE NOT NULL,
    service_name VARCHAR(255) NOT NULL,
    severity VARCHAR(10) DEFAULT 'P1',
    status VARCHAR(20) DEFAULT 'active',
    
    title TEXT,
    description TEXT,
    stack_trace TEXT,
    exception_type VARCHAR(255),
    file_path VARCHAR(500),
    line_number INTEGER,
    
    commit_hash VARCHAR(40),
    pr_number INTEGER,
    pr_url VARCHAR(500),
    author VARCHAR(255),
    
    root_cause TEXT,
    suggested_fix TEXT,
    rollback_command TEXT,
    confidence_score FLOAT DEFAULT 0.0,
    
    embedding vector(384),
    
    declared_at TIMESTAMP,
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    extra_metadata JSONB DEFAULT '{}'::jsonb,
    affected_services JSONB DEFAULT '[]'::jsonb,
    resolution_steps JSONB DEFAULT '[]'::jsonb
);

-- Indexes for faster queries
CREATE INDEX idx_incidents_incident_id ON incidents(incident_id);
CREATE INDEX idx_incidents_service_name ON incidents(service_name);
CREATE INDEX idx_incidents_status ON incidents(status);
CREATE INDEX idx_incidents_severity ON incidents(severity);
CREATE INDEX idx_incidents_declared_at ON incidents(declared_at);
CREATE INDEX idx_incidents_embedding ON incidents USING ivfflat (embedding vector_cosine_ops);

COMMENT ON TABLE incidents IS 'Stores all incidents with embeddings for RAG';
COMMENT ON COLUMN incidents.extra_metadata IS 'Additional incident metadata';
COMMENT ON COLUMN incidents.embedding IS '384-dim vector from sentence-transformers for similarity search';