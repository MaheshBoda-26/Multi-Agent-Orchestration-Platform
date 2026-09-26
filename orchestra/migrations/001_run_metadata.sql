-- Migration: Create run_metadata table for task analytics
-- Version: 1

CREATE TABLE IF NOT EXISTS run_metadata (
    run_id UUID PRIMARY KEY,
    task_id UUID NOT NULL,
    task_description TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'running',
    total_prompt_tokens INT DEFAULT 0,
    total_completion_tokens INT DEFAULT 0,
    total_cost_usd DECIMAL(10,6) DEFAULT 0,
    latency_ms INT DEFAULT 0,
    model_breakdown JSONB DEFAULT '{}',
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error TEXT,
    checkpoint_data JSONB
);

CREATE INDEX IF NOT EXISTS idx_run_metadata_task_id ON run_metadata(task_id);
CREATE INDEX IF NOT EXISTS idx_run_metadata_status ON run_metadata(status);
CREATE INDEX IF NOT EXISTS idx_run_metadata_started_at ON run_metadata(started_at);
