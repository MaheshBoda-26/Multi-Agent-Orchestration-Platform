from typing import List, Dict, Any
from pydantic import BaseModel
from llm.provider import LLMProvider
from .store import MemoryStore

class MemoryContext(BaseModel):
    """Structured context derived from retrieved memories."""
    relevant_past_tasks: List[Dict[str, Any]]
    suggested_approach: str
    known_constraints: List[str]

class MemoryRetriever:
    """Retrieves and synthesizes relevant memories for the planner."""
    
    def __init__(self, store: MemoryStore, llm: LLMProvider):
        self.store = store
        self.llm = llm

    async def retrieve(self, user_id: str, current_request: str) -> MemoryContext:
        # STUB: retrieval is not wired yet. The real implementation embeds the
        # request, queries the user's Chroma collection, and ranks the hits:
        #   embedding = await embedding_model.embed(current_request)
        #   hits = self.store.chroma.query(embedding, filter={"user_id": user_id})
        similar_memories: list = []
        
        # 3. Synthesize memories into planning context
        if not similar_memories:
            return MemoryContext(
                relevant_past_tasks=[],
                suggested_approach="No relevant past tasks found. Proceed with standard planning.",
                known_constraints=[]
            )

        prompt = (
            f"Based on the following past experiences for the user, suggest the best approach "
            f"for the current request: '{current_request}'\n\n"
            f"Past Memories:\n{similar_memories}\n\n"
            "Extract: 1. A suggested approach, 2. Relevant past task IDs, 3. Known user preferences."
        )
        
        context = await self.llm.complete_structured(prompt, MemoryContext)
        return context
