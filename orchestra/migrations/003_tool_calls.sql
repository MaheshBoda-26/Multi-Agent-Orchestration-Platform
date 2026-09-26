-- Migration: Create tool_calls audit table (TRD section 4)
-- Version: 3

CREATE TABLE IF NOT EXISTS tool_calls (
    id BIGSERIAL PRIMARY KEY,
    task_id UUID,
    subtask_id TEXT,
    specialist TEXT,
    tool_name TEXT NOT NULL,
    arguments JSONB,
    result JSONB,
    status TEXT NOT NULL,
    error TEXT,
    latency_ms INT DEFAULT 0,
    sensitive BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_task_id ON tool_calls(task_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tool_name ON tool_calls(tool_name);
