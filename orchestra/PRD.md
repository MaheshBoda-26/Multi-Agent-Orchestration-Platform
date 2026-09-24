# PRD: Orchestra

Status: no PRD existed, so this is the first version.

## Open questions (answer before Phase 0 ends)
1. **Budget.** I assumed $30 to $60 of total LLM spend for build and evals. If yours is lower, the eval set shrinks from 100 tasks to about 50 and repeats drop from 3 to 2.
2. **Web search provider.** Proposed: Tavily (free tier). Confirm you have or can create an account.
3. **Cross-provider comparison.** The spec lists OpenAI and Anthropic. Do you have credits on both? If only one, the routing experiment compares model tiers from one provider.
4. **Public deployment.** Do you want a public URL for the trace explorer (needs a small VM, roughly $5 to $10 a month), or is a local `docker compose up` plus a video enough?

## Problem statement
Single-agent demos break on long tasks in four ways.
- They plan implicitly, so one bad step derails the run.
- They keep state in memory, so a crash loses everything.
- They have no approval step, so a wrong action (deleting a file, posting to a webhook) happens before anyone can stop it.
- They give no trace, so when a run fails you cannot tell which decision caused it.

Teams building agents also lack numbers. Nobody can say whether a multi-agent design beats a single agent on their tasks, or what the extra calls cost.

## What to build
Orchestra is a backend platform with two web screens. A user submits a complex task in plain language, for example "compare pgvector, ChromaDB and Qdrant for a 10M-document RAG workload and write a two-page recommendation". A supervisor agent splits it into a dependency-ordered plan. Specialist agents (research, data analysis, writer, code executor) run the subtasks, in parallel where dependencies allow, using registered tools. A reviewer agent scores every output before the run continues. When the supervisor's confidence is low, a step is sensitive, or a specialist fails twice, the run pauses and waits for a human to approve, modify, reject or take over. Runs survive worker crashes and resume from the last checkpoint. After each task the system stores lessons in long-term memory and uses them when planning similar tasks. Every decision is recorded as a trace that can be explored and replayed. An eval harness compares Orchestra against a single-agent baseline on 100 tasks and reports success rate, cost and latency.

## Targeted users
| User | Why they use it | What they need |
|---|---|---|
| Task submitter (developer or analyst) | Gets multi-step research and analysis done without watching each step | Plain-language input, live progress, final result, cost per task |
| Human reviewer | Stops wrong or risky actions before they run | Full context at the decision point, the agent's reasoning, past similar decisions, a way to ask the agent questions |
| Agent developer (you, the maintainer) | Finds out why a run failed and whether a change helped | Trace tree, replay with edited inputs, eval table with variance |
| Portfolio audience (hiring engineers) | Judges engineering quality in under 10 minutes | One-command run, architecture diagram, results table, short demo video |

The fourth group is not a product user, but it sets two constraints. The repo must run from a clean clone with one command, and every claim in the README must trace to a reproducible result.

## Features

### Must-have
| ID | Feature |
|---|---|
| M1 | Task intake API with async execution and live status (SSE) |
| M2 | Supervisor planning with validated, dependency-ordered plans (subtask, specialist, inputs, expected format, complexity, confidence) |
| M3 | Four specialists with per-specialist tool permissions |
| M4 | Tool registry with schemas, permissions, rate limits and a logged record of every call |
| M5 | Parallel execution of independent subtasks, sequential for dependent ones |
| M6 | Reviewer agent with a scored rubric, and a retry-with-feedback loop |
| M7 | Durable execution: kill a worker mid-run, the run resumes with no repeated completed steps |
| M8 | Human-in-the-loop with four levels (Notify, Approve action, Approve plan, Take over), pausing across restarts |
| M9 | Review page: context, proposed action, reasoning, approve / modify / reject / take over, clarification chat |
| M10 | Long-term memory: extract after task, retrieve at planning, importance score, per-user delete |
| M11 | OpenTelemetry tracing with spans stored in Postgres, and per-task token, cost and latency totals |
| M12 | Eval harness: 100 tasks, single-agent baseline, ablations, 3 runs per configuration |
| M13 | Sandboxed code execution (Docker, no network, resource limits) |
| M14 | Security suite: at least 25 prompt-injection and permission tests |
| M15 | Trace explorer UI (tree view, status colors, node detail with prompt and response) |
| M16 | Docker Compose deployment and a scripted demo |

### Nice-to-have (cut in this order when behind)
| ID | Feature |
|---|---|
| N1 | Memory consolidation and expiry |
| N2 | Public cloud deployment with a shareable explorer link |
| N3 | Aggregate cost dashboard (cost per task type, per agent, escalation trend) |
| N4 | Model routing experiment (cheap tier for easy subtasks, strong tier for planning and review) |
| N5 | MCP client for one external MCP server (the MCP server that exposes Orchestra tools stays in scope) |
| N6 | Replay with input edits and a diff view (basic replay stays in scope) |

## Goals and success metrics
| Goal | Metric | Target |
|---|---|---|
| Plans are usable | Share of 20 sample tasks producing a schema-valid plan | 95% or higher |
| Orchestration helps | Task success rate versus single-agent baseline on the eval set | Higher by a margin reported with variance. Any claim on the resume uses the measured number |
| Runs are durable | Kill-worker test: resumes without repeating completed steps | 100% over 20 kills |
| Reviewer works | Catch rate on deliberately bad outputs | 90% or higher |
| Human gate works | Each of the four decisions resumes the run correctly, including after a restart | 4 of 4 |
| Tools are safe | Injection and permission suite pass rate | 90% or higher after defenses, with the before number reported |
| API is responsive | `POST /tasks` p95 latency (enqueue only) | Under 200 ms |
| Costs are visible | Every task records tokens and USD by agent and model | 100% of tasks |
| Others can run it | Clean-machine `docker compose up` plus demo script | Works with no manual steps beyond `.env` |

## Out of scope
- Multi-tenant SaaS features: billing, organizations, self-service signup
- Fine-tuning or training any model
- Voice, image or video agents
- A custom vector database or a custom LLM gateway
- Kubernetes, autoscaling, multi-region
- Real payments or real outbound email. Sensitive actions use a mock webhook so the approval flow can be shown without side effects
- Mobile apps
- An agent marketplace or plugin system beyond the tool registry and MCP

## Constraints
- **Time:** 4 weeks, about 50 hours a week, about 28 working days
- **Team:** one developer, working in Cursor with prompt-based coding
- **Budget:** about $30 to $60 of LLM spend in total (assumed, see open question 1), and $0 to $10 a month for hosting
- **Hardware:** everything must run on one machine with 4 vCPU and 8 GB RAM
- **Quality:** no result goes in the README that the eval command cannot reproduce

## Assumptions
- Anthropic and OpenAI API keys are available.
- Docker Desktop or Docker Engine runs on the development machine.
- Tasks are text-only, research and analysis oriented, and finish in under 10 minutes each.
- One tenant with a few users is enough to demonstrate per-user memory isolation.
- Web search results can change between runs, so research tasks in the eval set are graded on structure and cited claims checked against fetched pages, not on exact wording.
- Model names live in `routing.yaml`, so a model change never needs a code change.
