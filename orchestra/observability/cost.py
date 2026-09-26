from typing import Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone
import asyncpg

@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost: float = 0.0

@dataclass
class TaskCost:
    task_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    agent_costs: Dict[str, TokenUsage] = field(default_factory=dict)
    
    def add_usage(self, agent: str, prompt: int, completion: int, cost: float):
        if agent not in self.agent_costs:
            self.agent_costs[agent] = TokenUsage()
        self.agent_costs[agent].prompt_tokens += prompt
        self.agent_costs[agent].completion_tokens += completion
        self.agent_costs[agent].total_cost += cost

    def total_prompt_tokens(self) -> int:
        return sum(u.prompt_tokens for u in self.agent_costs.values())

    def total_completion_tokens(self) -> int:
        return sum(u.completion_tokens for u in self.agent_costs.values())

    def total_cost(self) -> float:
        return sum(u.total_cost for u in self.agent_costs.values())

class CostTracker:
    """Tracks token usage and costs per task and per agent."""
    
    def __init__(self, pool: Optional[asyncpg.Pool] = None):
        self.pool = pool
        self.current_task: Optional[TaskCost] = None

    def start_task(self, task_id: str):
        self.current_task = TaskCost(task_id=task_id, start_time=datetime.now(timezone.utc))

    def record_llm_call(self, agent: str, model: str, prompt_tokens: int, 
                        completion_tokens: int, cost: float):
        if self.current_task:
            self.current_task.add_usage(agent, prompt_tokens, completion_tokens, cost)

    def finish_task(self) -> Optional[TaskCost]:
        if self.current_task:
            self.current_task.end_time = datetime.now(timezone.utc)
            return self.current_task
        return None

    async def persist(self, task_cost: TaskCost):
        if not self.pool:
            return
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO task_costs (task_id, start_time, end_time, total_prompt_tokens, 
                                      total_completion_tokens, total_cost, agent_breakdown)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (task_id) DO UPDATE SET
                    end_time = EXCLUDED.end_time,
                    total_prompt_tokens = EXCLUDED.total_prompt_tokens,
                    total_completion_tokens = EXCLUDED.total_completion_tokens,
                    total_cost = EXCLUDED.total_cost,
                    agent_breakdown = EXCLUDED.agent_breakdown
            """,
                task_cost.task_id,
                task_cost.start_time,
                task_cost.end_time,
                task_cost.total_prompt_tokens(),
                task_cost.total_completion_tokens(),
                task_cost.total_cost(),
                str({k: v.__dict__ for k, v in task_cost.agent_costs.items()})
            )

async def init_cost_table(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS task_costs (
                task_id VARCHAR(255) PRIMARY KEY,
                start_time TIMESTAMP WITH TIME ZONE,
                end_time TIMESTAMP WITH TIME ZONE,
                total_prompt_tokens INTEGER,
                total_completion_tokens INTEGER,
                total_cost DECIMAL(10, 6),
                agent_breakdown JSONB
            );
        """)
