import json

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from graph.build import OrchestraGraph
from llm.fake import FakeProvider
from llm.recording import RecordingLLMProvider, RunRecorder


def _turn(answer: str) -> str:
    return json.dumps({"thought": "working", "final_answer": answer})


def _review(decision: str, scores: dict) -> str:
    return json.dumps({
        "scores": scores,
        "feedback": "missing detail on the second point",
        "decision": decision,
        "retry_instructions": "add detail",
    })


PLAN = json.dumps({
    "tasks": [
        {"id": "t1", "description": "summarize findings", "specialist": "researcher", "dependencies": []}
    ],
    "reasoning": "one subtask",
    "confidence": 0.9,
})

BAD_SCORES = {"correctness": 0.3, "completeness": 0.3, "format": 0.4, "sources": 0.2}
GOOD_SCORES = {"correctness": 0.9, "completeness": 0.9, "format": 0.9, "sources": 0.8}

BASE_STATE = {
    "task_id": "review-loop-task",
    "task_description": "summarize findings",
    "plan": None,
    "results": {},
    "attempts": {},
    "review_feedback": {},
    "shared_context": "",
    "final_response": None,
}


@pytest.mark.asyncio
async def test_bad_output_is_caught_retried_and_traced(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr("observability.spans.trace.get_tracer", provider.get_tracer)

    fake = FakeProvider()
    # Order matters: first matching key wins per prompt.
    fake.set_scripted_response("Reviewer feedback", _turn("improved answer"))
    fake.set_scripted_response("Role:", _turn("bad answer"))
    fake.set_scripted_response("bad answer", _review("retry", BAD_SCORES))
    fake.set_scripted_response("improved answer", _review("accept", GOOD_SCORES))
    fake.set_scripted_response("Orchestra Supervisor", PLAN)

    recorder = RunRecorder()
    graph = OrchestraGraph(RecordingLLMProvider(fake, recorder))

    final = await graph.workflow.ainvoke(BASE_STATE)

    result = final["results"]["t1"]
    assert result.status == "accepted"
    assert result.content == "improved answer"
    assert result.retry_count == 2, "the retry should count as the second attempt"

    names = [span.name for span in exporter.get_finished_spans()]
    assert names.count("specialist.run") == 2, names
    assert names.count("reviewer.review") == 2, names
    assert sum(1 for n in names if n.startswith("llm.")) >= 5
    assert recorder.prompt_tokens > 0
