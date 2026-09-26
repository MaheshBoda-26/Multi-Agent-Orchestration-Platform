-- Migration: Create tasks table (TRD section 4)
-- Version: 2

CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY,
    user_id VARCHAR(255),
    request TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'queued',
    plan JSONB,
    result JSONB,
    error TEXT,
    run_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
