-- Migration: eval harness tables (Task 34)
-- Version: 7
-- llm_cache deduplicates identical (model, role, prompt) calls across configs
-- and repeats; eval_runs + eval_results record every graded attempt so the
-- report is reproducible from the database alone.

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key VARCHAR(64) PRIMARY KEY,
    model VARCHAR(255) NOT NULL,
    role VARCHAR(50),
    prompt TEXT NOT NULL,
    response TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS eval_runs (
    run_id BIGSERIAL PRIMARY KEY,
    config_name VARCHAR(100) NOT NULL,
    repeat_index INT NOT NULL,
    provider VARCHAR(50) NOT NULL DEFAULT 'fake',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    UNIQUE (config_name, repeat_index, provider)
);

CREATE TABLE IF NOT EXISTS eval_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES eval_runs(run_id) ON DELETE CASCADE,
    task_id VARCHAR(100) NOT NULL,
    family VARCHAR(50) NOT NULL,
    passed BOOLEAN NOT NULL,
    score DOUBLE PRECISION NOT NULL,
    deterministic_passed BOOLEAN NOT NULL,
    judge_overall DOUBLE PRECISION,
    cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    latency_ms INT NOT NULL DEFAULT 0,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_eval_results_run ON eval_results(run_id);
CREATE INDEX IF NOT EXISTS idx_eval_results_family ON eval_results(family);
