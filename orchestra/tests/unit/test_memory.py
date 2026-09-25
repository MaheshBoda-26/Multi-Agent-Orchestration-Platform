import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from memory.store import MemoryStore, MemoryEntry, init_memory_table
from memory.extract import MemoryExtractor, MemoryExtraction
from memory.retrieve import MemoryRetriever, MemoryContext
from llm.fake import FakeProvider

@pytest.fixture
def mock_pool():
    pool = MagicMock()
    conn = AsyncMock()
    pool.acquire = AsyncMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn)))
    # Mock Postgres RETURNING id
    conn.fetchrow = AsyncMock(return_value={'id': 1})
    conn.execute = AsyncMock()
    return pool

@pytest.fixture
def mock_chroma():
    chroma = MagicMock()
    collection = MagicMock()
    chroma.get_or_create_collection.return_value = collection
    return chroma

@pytest.mark.asyncio
async def test_memory_store_save(mock_pool, mock_chroma):
    store = MemoryStore(mock_pool, mock_chroma)
    entry = MemoryEntry(
        user_id="user1",
        task_id="task1",
        request="test req",
        approach="test app",
        tools_used=["tool1"],
        outcome="success",
        facts=["fact1"],
        embedding=[0.1, 0.2]
    )
    
    saved = await store.save_memory(entry)
    assert saved.id == 1
    mock_pool.acquire.assert_called()
    mock_chroma.get_or_create_collection.assert_called_with("orchestra_memories")

@pytest.mark.asyncio
async def test_memory_extraction(mock_pool, mock_chroma):
    provider = FakeProvider()
    extractor = MemoryExtractor(provider)
    
    # Script the extraction response
    provider.set_scripted_response(
        "extraction",
        '{"approach": "Search and summarize", "tools_used": ["web_search"], "outcome": "Success", "facts": ["Fact A"], "preferences": ["None"]}'
    )
    
    # The prompt sent to LLM contains the word "extraction" in the instructions
    entry = await extractor.extract(
        user_id="u1", task_id="t1", 
        request="req", results=["res1"], final_response="final"
    )
    
    assert entry.approach == "Search and summarize"
    assert "web_search" in entry.tools_used
    assert entry.outcome == "Success"

@pytest.mark.asyncio
async def test_memory_retrieval_empty(mock_pool, mock_chroma):
    provider = FakeProvider()
    store = MemoryStore(mock_pool, mock_chroma)
    retriever = MemoryRetriever(store, provider)
    
    context = await retriever.retrieve("user1", "some request")
    assert context.relevant_past_tasks == []
    assert "No relevant past tasks" in context.suggested_approach
