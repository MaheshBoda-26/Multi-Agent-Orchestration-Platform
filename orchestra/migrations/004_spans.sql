-- Migration: Create spans table for OpenTelemetry export (D6)
-- Version: 4

CREATE TABLE IF NOT EXISTS spans (
    trace_id VARCHAR(32) NOT NULL,
    span_id VARCHAR(16) NOT NULL,
    parent_span_id VARCHAR(16),
    name VARCHAR(255),
    kind VARCHAR(50),
    status VARCHAR(50),
    start_time TIMESTAMP WITH TIME ZONE,
    end_time TIMESTAMP WITH TIME ZONE,
    attributes JSONB,
    events JSONB,
    resource JSONB,
    PRIMARY KEY (trace_id, span_id)
);

CREATE INDEX IF NOT EXISTS idx_spans_trace_id ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_name ON spans(name);
