# Phase 5 Design: Complete Orchestra Platform

**Date:** 2026-09-25
**Status:** Approved for Implementation

---

## Executive Summary

Build out the 5 remaining pillars sequentially:
1. **Durability** - LangGraph PostgreSQL checkpoints + run_metadata table
2. **Observability** - OpenTelemetry tracing with cost/token tracking
3. **Sandbox** - Real Docker-based code execution
4. **Memory** - Long-term memory with extraction/retrieval
5. **Evaluation** - OpenRouter-based eval harness + Trace Explorer UI

All LLM calls route through **OpenRouter** with model routing config.

---

## 1. Durability (M7)

### Architecture
- **LangGraph PostgresSaver** for checkpoint persistence (standard tables)
- **Custom `run_metadata` table** for analytics: task_id, status, total_tokens, total_cost, latency_ms, model_breakdown, started_at, completed_at
- **Resume capability**: Kill worker mid-run → restart → continues from last checkpoint without repeating completed steps

### Components
```
orchestra/graph/
├── checkpointer.py      # PostgresSaver setup + custom metadata persistence
├── state.py             # Add checkpoint-compatible state serialization
└── build.py             # Compile graph with checkpointer
```

### Schema: `run_metadata`
```sql
CREATE TABLE run_metadata (
    run_id UUID PRIMARY KEY,
    task_id UUID NOT NULL,
    task_description TEXT NOT NULL,
    status VARCHAR(50) NOT NULL,  -- running, completed, failed, paused
    total_prompt_tokens INT DEFAULT 0,
    total_completion_tokens INT DEFAULT 0,
    total_cost_usd DECIMAL(10,6) DEFAULT 0,
    latency_ms INT DEFAULT 0,
    model_breakdown JSONB DEFAULT '{}',  -- {"model-name": {"prompt": N, "completion": N, "cost": X}}
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error TEXT,
    checkpoint_data JSONB  -- last successful checkpoint for debugging
);
CREATE INDEX idx_run_metadata_task_id ON run_metadata(task_id);
CREATE INDEX idx_run_metadata_status ON run_metadata(status);
```

### Acceptance
- Kill test: 20 runs, kill worker at random point → all resume without repeating completed steps
- Cost/tokens recorded per run in `run_metadata`

---

## 2. Observability (M11)

### Architecture
- **OpenTelemetry** with PostgreSQL span exporter
- **Span attributes**: agent_name, task_id, subtask_id, model, tokens_prompt, tokens_completion, cost_usd, duration_ms, status
- **Cost tracking**: Integrated into LLM provider abstraction - every call records tokens + cost

### Components
```
orchestra/observability/
├── __init__.py
├── tracing.py           # OpenTelemetry setup, span processor, Postgres exporter
├── metrics.py           # Cost/token aggregation, per-agent/model breakdown
└── exporter.py          # Custom Postgres span exporter
```

### Schema: `traces`
```sql
CREATE TABLE traces (
    trace_id VARCHAR(32) NOT NULL,
    span_id VARCHAR(16) NOT NULL,
    parent_span_id VARCHAR(16),
    name VARCHAR(255) NOT NULL,
    kind VARCHAR(50),  -- LLM, TOOL, AGENT, REVIEW, HITL
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ,
    duration_ms INT,
    status VARCHAR(20),  -- ok, error
    attributes JSONB DEFAULT '{}',
    events JSONB DEFAULT '[]',
    task_id UUID,
    subtask_id VARCHAR(100),
    agent_name VARCHAR(50),
    model VARCHAR(100),
    tokens_prompt INT DEFAULT 0,
    tokens_completion INT DEFAULT 0,
    cost_usd DECIMAL(10,6) DEFAULT 0
);
CREATE INDEX idx_traces_task_id ON traces(task_id);
CREATE INDEX idx_traces_trace_id ON traces(trace_id);
```

### LLM Provider Cost Integration
```python
# In provider.complete() and complete_structured():
response = await self._call_api(prompt, model)
cost = self._calculate_cost(response.tokens_prompt, response.tokens_completion, model)
# Record to OpenTelemetry span + run_metadata
```

### Acceptance
- Every LLM call produces a span with tokens/cost
- Per-task totals in `run_metadata` match sum of spans
- Query: "Show me cost breakdown by agent for last 10 runs"

---

## 3. Sandbox (M13)

### Architecture
- **Docker-based execution** with `python:3.11-slim` base
- **Network isolation**: No network access (disabled in container)
- **Resource limits**: CPU=1, Memory=512MB, Pids=50, Timeout=60s
- **Filesystem jail**: Mount workspace as read-only + writable /tmp
- **Async execution**: Submit → poll → retrieve result

### Components
```
orchestra/tools/builtin/
├── sandbox.py           # DockerSandbox class (replaces simulation)
└── docker_utils.py      # Container lifecycle, health checks

orchestra/tools/
└── sandbox_pool.py      # Pool of pre-warmed containers for low latency
```

### Docker Config
```python
DOCKER_CONFIG = {
    "image": "orchestra-sandbox:latest",  # Built from Dockerfile.sandbox
    "network_mode": "none",
    "cpu_quota": 100000,  # 1 CPU
    "mem_limit": "512m",
    "pids_limit": 50,
    "read_only": True,
    "tmpfs": {"/tmp": "rw,noexec,nosuid,size=100m"},
    "volumes": {
        "/host/workspace": {"bind": "/workspace", "mode": "ro"}
    },
    "security_opt": ["no-new-privileges:true"]
}
```

### Dockerfile.sandbox
```dockerfile
FROM python:3.11-slim
RUN pip install --no-cache-dir numpy pandas requests httpx
WORKDIR /workspace
```

### Acceptance
- Execute arbitrary Python → returns stdout/stderr
- Network blocked (requests fail)
- Resource limits enforced (OOM → container killed, returns error)
- Latency < 2s for warm container, < 5s cold start

---

## 4. Long-Term Memory (M10)

### Architecture
- **PostgreSQL with pgvector** for semantic search
- **Extraction**: After task completion, LLM extracts key facts/patterns
- **Storage**: Embeddings + metadata (user_id, task_type, importance, tags)
- **Retrieval**: At planning time, supervisor queries relevant memories

### Components
```
orchestra/memory/
├── __init__.py
├── store.py             # Vector store operations (pgvector)
├── extractor.py         # LLM-based fact extraction from completed runs
├── retriever.py         # Semantic search + relevance ranking
└── models.py            # MemoryEntry, ExtractionResult
```

### Schema: `memories`
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(100) NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(1536),  -- OpenAI text-embedding-3-small
    metadata JSONB DEFAULT '{}',  -- {"task_type": "...", "tags": [...], "source_task_id": "..."}
    importance FLOAT DEFAULT 0.5,  -- 0.0 to 1.0
    created_at TIMESTAMPTZ DEFAULT NOW(),
    accessed_at TIMESTAMPTZ DEFAULT NOW(),
    access_count INT DEFAULT 0
);
CREATE INDEX idx_memories_user_id ON memories(user_id);
CREATE INDEX idx_memories_embedding ON memories USING hnsw (embedding vector_cosine_ops);
```

### Extraction Prompt
```
Extract 3-5 key reusable insights from this completed task.
Format: JSON array of {"fact": "...", "context": "...", "tags": [...], "importance": 0.0-1.0}
Focus on: patterns, tool usage tips, domain knowledge, common pitfalls.
```

### Retrieval at Planning
```python
# In Supervisor.create_plan():
relevant_memories = await retriever.search(task_description, user_id, k=5)
prompt += "\nRelevant past experiences:\n" + format_memories(relevant_memories)
```

### Acceptance
- After task, 3-5 memories extracted and stored
- Planning retrieves relevant memories (cosine similarity > 0.7)
- Per-user isolation enforced
- Delete endpoint for user data removal

---

## 5. Evaluation Harness (M12) + Trace Explorer UI (M15)

### 5.1 Eval Harness Architecture

```
orchestra/evals/
├── __init__.py
├── dataset.py           # 100 TaskDataset (load from JSONL)
├── runner.py            # Run Orchestra vs Single-Agent baseline
├── baseline.py          # Single-agent implementation for comparison
├── scoring.py           # Judge LLM evaluates outputs (structure + cited claims)
├── ablations.py         # Config variants: no-reviewer, no-parallel, no-memory, etc.
├── reporter.py          # Statistical analysis, variance, markdown report
└── models.py            # Task, Result, EvalConfig, AblationConfig
```

### OpenRouter Provider
```python
# orchestra/llm/openrouter.py
class OpenRouterProvider(LLMProvider):
    """Routes to OpenRouter with model aliases from routing.yaml"""
    
    MODEL_ALIASES = {
        "planner": "anthropic/claude-3.5-sonnet",
        "reviewer": "anthropic/claude-3.5-sonnet", 
        "specialist": "openai/gpt-4o-mini",
        "memory_extractor": "openai/gpt-4o-mini",
        "eval_judge": "anthropic/claude-3.5-sonnet",
        "cheap": "meta-llama/llama-3.1-8b-instruct:free",
    }
```

### routing.yaml
```yaml
models:
  planner: "anthropic/claude-3.5-sonnet"
  reviewer: "anthropic/claude-3.5-sonnet"
  researcher: "openai/gpt-4o-mini"
  data_analyst: "openai/gpt-4o-mini"
  writer: "openai/gpt-4o-mini"
  code_executor: "openai/gpt-4o-mini"
  memory_extractor: "openai/gpt-4o-mini"
  eval_judge: "anthropic/claude-3.5-sonnet"
  cheap: "meta-llama/llama-3.1-8b-instruct:free"

routing_rules:
  - if: "task.complexity == 'high'"
    use: "planner"
  - if: "agent == 'reviewer'"
    use: "reviewer"
  - if: "agent in ['researcher', 'data_analyst', 'writer', 'code_executor']"
    use: "specialist"
  - if: "agent == 'memory_extractor'"
    use: "memory_extractor"
  - if: "eval_mode == 'ablation_cheap'"
    use: "cheap"
```

### Dataset: 100 Tasks (evals/dataset.jsonl)
Categories (20 each):
- **Research**: "Compare X vs Y for Z use case"
- **Analysis**: "Analyze this dataset and find patterns"
- **Writing**: "Write a technical report on X"
- **Coding**: "Write Python script to do X"
- **Multi-step**: "Research X, analyze data, write recommendation"

### Baseline: Single Agent
```python
class SingleAgentBaseline:
    async def run(self, task: str) -> Result:
        # One LLM call with all tools available
        # No planning, no review, no parallel, no memory
```

### Ablations (3 runs each):
1. Full Orchestra (default)
2. No reviewer (accept all outputs)
3. No parallel (sequential only)
4. No memory (disable retrieval)
5. No HITL (auto-approve all)
6. Cheap models only (all agents use `cheap` model)

### Scoring (Judge LLM)
```python
JUDGE_PROMPT = """
Evaluate the output for this task. Score 0-10 on:
1. Correctness: Factual accuracy, no hallucinations
2. Completeness: Addresses all task requirements
3. Structure: Clear organization, professional format
4. Sources: Quality of citations, evidence
Return JSON: {"scores": {...}, "overall": X, "passes": true/false, "reasoning": "..."}
"""
```

### 5.2 Trace Explorer UI (M15)

**Two Views in One App:**

| View | Audience | Features |
|------|----------|----------|
| **Technical** | Agent Developers | Tree view, span details (prompt/response), replay with edits, cost breakdown |
| **Simple** | Task Submitters | Progress timeline, cost summary, final result, approval history |

### Components
```
orchestra/web/
├── trace_explorer.py    # FastAPI routes for trace data
├── static/
│   ├── explorer.js      # Tree view, span panel, replay
│   ├── explorer.css
│   └── simple_view.js   # Simplified progress view
└── templates/
    ├── explorer.html    # Technical view
    └── simple.html      # Simple view
```

### API Endpoints
```
GET  /traces/{task_id}           # Full trace tree
GET  /traces/{task_id}/span/{span_id}  # Span detail (prompt, response, attrs)
POST /traces/{task_id}/replay    # Replay with edited input
GET  /tasks/{task_id}/simple     # Simple view data
GET  /analytics/costs            # Cost dashboard data
```

### Acceptance
- Eval runs 100 tasks × 6 configs × 3 runs = 1,800 runs
- Produces markdown report with mean ± std, statistical significance
- Trace explorer loads in < 2s, tree renders 1000+ spans
- Replay produces different result when input edited

---

## Implementation Order

### Phase 5a: Durability (Week 1)
1. Add `run_metadata` table + migration
2. Implement `PostgresSaver` in `graph/checkpointer.py`
3. Wire checkpointer into `OrchestraGraph.build()`
4. Add `run_metadata` persistence in `api/server.py` task lifecycle
5. Kill-test script: `scripts/test_durability.py`

### Phase 5b: Observability (Week 1-2)
1. Add `traces` table + migration
2. Implement OpenTelemetry setup in `observability/tracing.py`
3. Custom Postgres span exporter in `observability/exporter.py`
4. Instrument LLM provider + tool registry + graph nodes
5. Cost aggregation in `observability/metrics.py`

### Phase 5c: Sandbox (Week 2)
1. Create `Dockerfile.sandbox`
2. Implement `DockerSandbox` class in `tools/builtin/sandbox.py`
3. Add `SandboxPool` for warm containers
4. Replace fake `CodeExecutionTool` with real Docker version
5. Security test suite

### Phase 5d: Memory (Week 2-3)
1. Add pgvector extension + `memories` table + migration
2. Implement `MemoryStore`, `MemoryExtractor`, `MemoryRetriever`
3. Wire extraction into `node_synthesize` (after task completes)
4. Wire retrieval into `Supervisor.create_plan()`
5. Add user_id to task context

### Phase 5e: Evaluation + UI (Week 3-4)
1. Create `evals/dataset.jsonl` (100 tasks)
2. Implement OpenRouter provider + routing.yaml
3. Build eval runner, baseline, ablations, judge
4. Build trace explorer API + frontend (two views)
5. Run full eval, generate report
6. Demo script: `scripts/demo.py`

---

## Open Questions Resolved

| Question | Decision |
|----------|----------|
| Build order | Sequential: Durability → Observability → Sandbox → Memory/Eval/UI |
| LLM Provider | OpenRouter primary with model routing config (routing.yaml) |
| Checkpoints | Hybrid: LangGraph PostgresSaver + custom run_metadata table |
| Eval Models | OpenRouter with free/cheap models for ablations |
| Trace UI | Two views: Technical (dev) + Simple (submitters) |

---

## Success Criteria (from PRD)

| Goal | Metric | Target |
|------|--------|--------|
| Plans valid | Schema-valid plans on 20 samples | 95%+ |
| Orchestration helps | Success rate vs baseline | Higher with variance |
| Runs durable | Kill-worker resume test | 100% over 20 kills |
| Reviewer works | Catch bad outputs | 90%+ |
| Human gate works | 4 decisions resume correctly | 4 of 4 |
| Tools safe | Injection/permission suite | 90%+ after defenses |
| API responsive | POST /tasks p95 | < 200ms |
| Costs visible | Tokens/USD per task/agent/model | 100% |
| Runnable | `docker compose up` + demo | Zero manual steps |

---

## Dependencies

Add to `pyproject.toml`:
```toml
[project.optional-dependencies]
eval = [
    "openrouter-client>=0.1.0",
    "pgvector>=0.2.0",
    "opentelemetry-api>=1.20",
    "opentelemetry-sdk>=1.20",
    "opentelemetry-exporter-otlp>=1.20",
    "opentelemetry-instrumentation-fastapi>=0.40",
    "docker>=7.0",
    "httpx>=0.27",
]
```

---

## Next Steps

1. **User reviews this spec** → approve or request changes
2. **Invoke `writing-plans` skill** to create detailed implementation plan
3. **Begin Phase 5a: Durability**