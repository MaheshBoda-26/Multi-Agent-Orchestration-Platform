import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from graph.build import OrchestraGraph
from llm.fake import FakeProvider
from llm.recording import RecordingLLMProvider, RunRecorder

BASE_STATE = {
    "task_id": "span-test-task",
    "task_description": "research and write",
    "plan": None,
    "results": {},
    "attempts": {},
    "review_feedback": {},
    "shared_context": "",
    "final_response": None,
}


@pytest.mark.asyncio
async def test_graph_emits_span_per_agent_and_model_call(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    # Avoid global tracer-provider state: route the helper at our provider.
    monkeypatch.setattr("observability.spans.trace.get_tracer", provider.get_tracer)

    recorder = RunRecorder()
    graph = OrchestraGraph(RecordingLLMProvider(FakeProvider(), recorder))

    final = await graph.workflow.ainvoke(BASE_STATE)

    assert final["final_response"]
    names = [span.name for span in exporter.get_finished_spans()]
    for expected in ("supervisor.plan", "specialist.run", "reviewer.review", "synthesize"):
        assert expected in names, f"missing span {expected}: {names}"
    assert any(name.startswith("llm.") for name in names), names
    assert recorder.prompt_tokens > 0
    assert recorder.cost_usd == 0.0  # FakeProvider is free
    assert "fake-model-v1" in recorder.model_breakdown
