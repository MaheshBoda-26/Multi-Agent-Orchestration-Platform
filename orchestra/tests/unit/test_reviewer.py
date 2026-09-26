import pytest
from pydantic import BaseModel
from agents.reviewer import ReviewerAgent, ReviewScore
from llm.fake import FakeProvider

class MockModel(BaseModel):
    scores: ReviewScore
    feedback: str
    decision: str
    retry_instructions: str = ""

@pytest.mark.asyncio
async def test_reviewer_accepts_high_quality():
    provider = FakeProvider()
    reviewer = ReviewerAgent(provider, threshold=0.7)
    
    # Script a high-quality response
    provider.set_scripted_response(
        "review",
        '{"scores": {"correctness": 0.9, "completeness": 0.8, "format": 0.9, "sources": 0.8}, '
        '"feedback": "Excellent work", "decision": "accept", "retry_instructions": ""}'
    )
    
    result = await reviewer.review("test task", "great output", "researcher")
    assert result.decision == "accept"
    assert result.scores.overall() >= 0.7

@pytest.mark.asyncio
async def test_reviewer_rejects_low_quality():
    provider = FakeProvider()
    reviewer = ReviewerAgent(provider, threshold=0.7)
    
    # Script a low-quality response
    provider.set_scripted_response(
        "review",
        '{"scores": {"correctness": 0.4, "completeness": 0.3, "format": 0.5, "sources": 0.2}, '
        '"feedback": "Poor quality", "decision": "retry", "retry_instructions": "Add more detail"}'
    )
    
    result = await reviewer.review("test task", "bad output", "researcher")
    assert result.decision == "retry"
    assert result.scores.overall() < 0.7

@pytest.mark.asyncio
async def test_reviewer_overrides_mismatched_decision():
    provider = FakeProvider()
    reviewer = ReviewerAgent(provider, threshold=0.7)
    
    # LLM says "accept" but scores are low
    provider.set_scripted_response(
        "review",
        '{"scores": {"correctness": 0.4, "completeness": 0.3, "format": 0.5, "sources": 0.2}, '
        '"feedback": "Actually bad", "decision": "accept", "retry_instructions": ""}'
    )
    
    result = await reviewer.review("test task", "bad output", "researcher")
    # Should override to retry
    assert result.decision == "retry"
