"""Long-term memory on pgvector (Phase 5).

Extraction turns a completed run into one durable lesson string; retrieval
finds the most relevant past lessons for a user and synthesizes planning
context. Everything is scoped per user and search is cosine top-k over
memories.embedding (see memory.store).
"""
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from llm.provider import LLMProvider
from memory.store import (
    MemoryRecord,
    list_user_memories,
    save_memory,
    search_memories,
)

logger = logging.getLogger(__name__)

TOP_K = 5


class MemoryExtraction(BaseModel):
    """The structured output of the memory extraction process."""
    approach: str = Field(description="The strategy used to solve the task")
    tools_used: List[str] = Field(description="The specific tools that were most effective")
    outcome: str = Field(description="Whether the task succeeded and why")
    facts: List[str] = Field(description="Key factual insights discovered")
    preferences: List[str] = Field(description="Observed user preferences or constraints")


class MemoryContext(BaseModel):
    """Structured context derived from retrieved memories."""
    relevant_past_tasks: List[Dict[str, Any]] = Field(default_factory=list)
    suggested_approach: str = ""
    known_constraints: List[str] = Field(default_factory=list)


class MemoryExtractor:
    """Analyzes a completed task and stores one lesson per run."""

    def __init__(self, llm: LLMProvider, pool: Any, embeddings: Any) -> None:
        self.llm = llm
        self.pool = pool
        self.embeddings = embeddings

    async def extract(
        self,
        user_id: str,
        task_id: str,
        request: str,
        results: List[str],
        final_response: str,
    ) -> Optional[MemoryRecord]:
        prompt = (
            "You are a memory extraction agent. Your goal is to analyze a completed task "
            "and extract a concise, high-value summary for long-term storage.\n\n"
            f"User Request: {request}\n\n"
            f"Execution Results:\n{chr(10).join(results)}\n\n"
            f"Final Response: {final_response}\n\n"
            "Extract the following:\n"
            "1. Approach: How was this solved? (e.g., 'used search then validated with code')\n"
            "2. Tools: Which tools were critical?\n"
            "3. Outcome: Was it successful? What were the key results?\n"
            "4. Facts: What new facts were discovered that are worth remembering?\n"
            "5. Preferences: Did the user show any specific preferences or constraints?\n\n"
            "Return a structured JSON object."
        )
        extraction = await self.llm.complete_structured(
            prompt, MemoryExtraction, role="extractor"
        )

        content = (
            f"Request: {request}\n"
            f"Approach: {extraction.approach}\n"
            f"Tools: {', '.join(extraction.tools_used) or 'none'}\n"
            f"Outcome: {extraction.outcome}\n"
            f"Facts: {'; '.join(extraction.facts) or 'none'}\n"
            f"Preferences: {'; '.join(extraction.preferences) or 'none'}"
        )
        record_id = await save_memory(
            self.pool,
            self.embeddings,
            user_id=user_id or "anonymous",
            content=content,
            kind="task_lesson",
            importance=0.5,
            source_task_id=task_id,
        )
        logger.info("Stored memory %s for task %s", record_id, task_id)
        return MemoryRecord(
            id=record_id,
            user_id=user_id or "anonymous",
            kind="task_lesson",
            content=content,
            importance=0.5,
            access_count=0,
            source_task_id=task_id,
            created_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        )


class MemoryRetriever:
    """Retrieves and synthesizes relevant memories for the planner."""

    def __init__(self, llm: LLMProvider, pool: Any, embeddings: Any) -> None:
        self.llm = llm
        self.pool = pool
        self.embeddings = embeddings

    async def retrieve(
        self, user_id: str, current_request: str
    ) -> MemoryContext:
        memories = await search_memories(
            self.pool, self.embeddings, user_id=user_id, query=current_request,
            top_k=TOP_K,
        )
        if not memories:
            return MemoryContext(
                relevant_past_tasks=[],
                suggested_approach=(
                    "No relevant past tasks found. Proceed with standard planning."
                ),
                known_constraints=[],
            )

        relevant = [
            {
                "memory_id": m.id,
                "content": m.content,
                "similarity": round(m.similarity, 3),
            }
            for m in memories
        ]
        prompt = (
            f"Based on the following past experiences for the user, suggest the best approach "
            f"for the current request: '{current_request}'\n\n"
            f"Past Memories:\n{relevant}\n\n"
            "Extract: 1. A suggested approach, 2. Relevant memory ids, 3. Known user preferences."
        )
        context = await self.llm.complete_structured(
            prompt, MemoryContext, role="supervisor"
        )
        context.relevant_past_tasks = relevant
        return context


__all__ = [
    "MemoryContext",
    "MemoryExtraction",
    "MemoryExtractor",
    "MemoryRetriever",
    "list_user_memories",
]
