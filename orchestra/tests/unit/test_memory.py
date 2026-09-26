"""Memory on pgvector: extraction stores, retrieval scopes per user,
deletion removes everything, similar text ranks first with FakeEmbedding."""
import uuid

import pytest

from llm.embeddings import FakeEmbedding
from memory.retrieve import MemoryExtractor, MemoryRetriever
from memory.store import (
    delete_user_memories,
    list_user_memories,
    save_memory,
    search_memories,
)
from llm.fake import FakeProvider


_TEST_USERS = tuple(f"mem-user-{uuid.uuid4()}" for _ in range(7))


def _users():
    """Unique per-run user ids; the table is truncated in the module fixture."""
    return dict(zip(
        ("u1", "ua", "ub", "udel", "ux", "ur", "unone"), _TEST_USERS,
        strict=True,
    ))


@pytest.mark.asyncio
async def test_save_and_search_roundtrip(postgres_pool):
    users = _users()
    embeddings = FakeEmbedding()
    memory_id = await save_memory(
        postgres_pool, embeddings,
        user_id=users["u1"],
        content="Compare vector databases using web search then validate with code.",
        source_task_id="task-1",
    )
    assert memory_id > 0

    hits = await search_memories(
        postgres_pool, embeddings,
        user_id=users["u1"],
        query="Compare vector databases using web search then validate with code.",
    )
    assert hits, "identical text must retrieve the stored memory"
    assert hits[0].id == memory_id
    assert hits[0].similarity > 0.99
    assert hits[0].access_count == 1, "retrieval bumps access_count"


@pytest.mark.asyncio
async def test_search_is_scoped_per_user(postgres_pool):
    users = _users()
    embeddings = FakeEmbedding()
    await save_memory(
        postgres_pool, embeddings,
        user_id=users["ua"], content="Financial quarterly report analysis.",
    )
    await save_memory(
        postgres_pool, embeddings,
        user_id=users["ub"], content="Quarterly report analysis for finance.",
    )

    hits_a = await search_memories(
        postgres_pool, embeddings, user_id=users["ua"],
        query="Quarterly report analysis for finance.",
    )
    assert all(h.user_id == users["ua"] for h in hits_a)
    assert hits_a and hits_a[0].content.startswith("Financial quarterly")


@pytest.mark.asyncio
async def test_delete_user_memories_removes_everything(postgres_pool):
    users = _users()
    embeddings = FakeEmbedding()
    for i in range(3):
        await save_memory(
            postgres_pool, embeddings,
            user_id=users["udel"], content=f"Lesson number {i} about deploy pipelines.",
        )
    assert len(await list_user_memories(postgres_pool, users["udel"])) == 3

    deleted = await delete_user_memories(postgres_pool, users["udel"])
    assert deleted == 3
    assert await list_user_memories(postgres_pool, users["udel"]) == []
    # The vector rows are gone too: nothing retrieves.
    hits = await search_memories(
        postgres_pool, embeddings, user_id=users["udel"],
        query="Lesson number 0 about deploy pipelines.",
    )
    assert hits == []


@pytest.mark.asyncio
async def test_extractor_stores_one_lesson(postgres_pool):
    users = _users()
    provider = FakeProvider()
    extractor = MemoryExtractor(provider, postgres_pool, FakeEmbedding())

    record = await extractor.extract(
        user_id=users["ux"], task_id="task-x",
        request="req", results=["res1"], final_response="final",
    )
    assert record.id > 0
    stored = await list_user_memories(postgres_pool, users["ux"])
    assert len(stored) == 1
    assert "Approach:" in stored[0].content
    assert stored[0].source_task_id == "task-x"


@pytest.mark.asyncio
async def test_retriever_surfaces_past_lessons(postgres_pool):
    users = _users()
    embeddings = FakeEmbedding()
    provider = FakeProvider()
    await save_memory(
        postgres_pool, embeddings,
        user_id=users["ur"],
        content="Research pipeline: web_search then writer polish worked well.",
    )
    retriever = MemoryRetriever(provider, postgres_pool, embeddings)

    context = await retriever.retrieve(
        users["ur"], "Research pipeline: web_search then writer polish."
    )
    assert context.relevant_past_tasks, "similar request must surface the lesson"
    assert context.suggested_approach
    assert all("memory_id" in task for task in context.relevant_past_tasks)


@pytest.mark.asyncio
async def test_retriever_empty_state(postgres_pool):
    users = _users()
    retriever = MemoryRetriever(FakeProvider(), postgres_pool, FakeEmbedding())
    context = await retriever.retrieve(users["unone"], "anything at all")
    assert context.relevant_past_tasks == []
    assert "No relevant past tasks" in context.suggested_approach
