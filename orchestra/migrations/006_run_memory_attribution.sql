-- Migration: run_metadata memory attribution (Phase 5) + memories backfill guard
-- Version: 6
-- Which stored memories a run's plan leaned on; Phase 6 uses this to compare
-- with-memory vs without-memory success rates per task family.

ALTER TABLE run_metadata
    ADD COLUMN IF NOT EXISTS memory_ids_used JSONB NOT NULL DEFAULT '[]';
