import pytest
import asyncio
from llm.fake import FakeProvider
from pydantic import BaseModel

class MockModel(BaseModel):
    answer: str
    confidence: float

@pytest.mark.asyncio
async def test_fake_provider_complete():
    provider = FakeProvider()
    prompt = "Hello"
    expected_response = "Hi there!"
    provider.set_scripted_response(prompt, expected_response)
    
    response = await provider.complete(prompt)
    assert response.content == expected_response
    assert response.model == "fake-model-v1"
    assert response.cost == 0.0

@pytest.mark.asyncio
async def test_fake_provider_complete_default():
    provider = FakeProvider()
    response = await provider.complete("Unknown prompt")
    assert response.content == provider.default_response

@pytest.mark.asyncio
async def test_fake_provider_structured():
    provider = FakeProvider()
    prompt = "Structured test"
    # Script a JSON response for the model
    provider.set_scripted_response(prompt, '{"answer": "Yes", "confidence": 0.9}')
    
    response = await provider.complete_structured(prompt, MockModel)
    assert isinstance(response, MockModel)
    assert response.answer == "Yes"
    assert response.confidence == 0.9

@pytest.mark.asyncio
async def test_fake_provider_structured_fallback():
    provider = FakeProvider()
    # Provide non-JSON response to trigger fallback
    provider.set_scripted_response("fail", "not json")
    
    response = await provider.complete_structured("fail", MockModel)
    assert isinstance(response, MockModel)
