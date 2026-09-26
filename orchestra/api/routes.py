from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone
import asyncpg
import json

class ApprovalRequest(BaseModel):
    id: str
    task_id: str
    escalation_level: str
    trigger: str
    context: Dict[str, Any]
    proposed_action: Optional[str] = None
    status: str = "pending"  # pending, approved, rejected, modified, taken_over
    created_at: datetime
    resolved_at: Optional[datetime] = None
    resolution: Optional[Dict[str, Any]] = None

class ApprovalDecision(BaseModel):
    action: str  # approve, reject, modify, take_over, clarify
    modified_action: Optional[str] = None
    clarification_question: Optional[str] = None

async def init_approval_table(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS approvals (
                id VARCHAR(255) PRIMARY KEY,
                task_id VARCHAR(255) NOT NULL,
                escalation_level VARCHAR(50) NOT NULL,
                trigger VARCHAR(100) NOT NULL,
                context JSONB NOT NULL,
                proposed_action TEXT,
                status VARCHAR(50) DEFAULT 'pending',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                resolved_at TIMESTAMP WITH TIME ZONE,
                resolution JSONB
            );
            CREATE INDEX IF NOT EXISTS idx_approvals_task_id ON approvals(task_id);
            CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
        """)

async def create_approval_request(pool: asyncpg.Pool, request: ApprovalRequest) -> ApprovalRequest:
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO approvals (id, task_id, escalation_level, trigger, context, proposed_action, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """,
            request.id, request.task_id, request.escalation_level, request.trigger,
            json.dumps(request.context), request.proposed_action, request.status, request.created_at
        )
    return request

async def get_pending_approvals(pool: asyncpg.Pool) -> List[ApprovalRequest]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at ASC
        """)
        return [ApprovalRequest(**dict(row)) for row in rows]

async def get_approval(pool: asyncpg.Pool, approval_id: str) -> Optional[ApprovalRequest]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM approvals WHERE id = $1", approval_id)
        if row:
            return ApprovalRequest(**dict(row))
        return None

async def resolve_approval(pool: asyncpg.Pool, approval_id: str, decision: ApprovalDecision) -> ApprovalRequest:
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE approvals 
            SET status = $1, resolved_at = $2, resolution = $3
            WHERE id = $4
        """, decision.action, datetime.now(timezone.utc), json.dumps(decision.model_dump()), approval_id)
        
        row = await conn.fetchrow("SELECT * FROM approvals WHERE id = $1", approval_id)
        return ApprovalRequest(**dict(row))

async def get_task_approvals(pool: asyncpg.Pool, task_id: str) -> List[ApprovalRequest]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM approvals WHERE task_id = $1 ORDER BY created_at ASC
        """, task_id)
        return [ApprovalRequest(**dict(row)) for row in rows]
