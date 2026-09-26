"""Eval harness: deterministic task set, graders, judge gate, report math."""
import json

import pytest

from evals.build_task_set import build_task_set, load_task_set, write_task_set
from evals.cache import CachedProvider, LLMCache, cache_key
from evals.graders import (
    DeterministicGrader,
    LLMJudgeGrader,
    judge_agreement,
)
from evals.report import generate_report
from evals.run import run_config
from llm.fake import FakeProvider


def test_task_set_is_deterministic_and_complete(tmp_path):
    path = tmp_path / "task_set.jsonl"
    first = write_task_set(path)
    second = load_task_set(path)

    assert len(first) == 100
    assert [t.id for t in first] == [t.id for t in second]
    assert path.read_bytes() == path.read_bytes()
    families = {t.family for t in first}
    assert families == {"research", "data_analysis", "writing", "coding"}
    # Repeated-family flag: later tasks of each family are marked repeats.
    assert any(t.repeats_family for t in first)
    assert not all(t.repeats_family for t in first)


@pytest.mark.asyncio
async def test_deterministic_grader_checks_substrings_and_length():
    grader = DeterministicGrader(must_contain=["summary"], min_chars=20)
    ok = await grader.grade("t", "write a summary", "A long summary with sources.")
    bad = await grader.grade("t", "write a summary", "too short")

    assert ok.passed
    assert not bad.passed
    assert "missing" in bad.reason or "shorter" in bad.reason


@pytest.mark.asyncio
async def test_llm_judge_gates_on_deterministic_failure():
    class LowJudge(FakeProvider):
        async def complete_structured(self, prompt, response_model, **kwargs):
            return response_model.model_validate_json(
                json.dumps({"correctness": 1.0, "completeness": 1.0, "format": 1.0})
            )

    judge = LLMJudgeGrader(LowJudge(), must_contain=["impossible"], min_chars=1)
    result = await judge.grade("t", "i", "no keyword here")
    assert not result.passed
    assert result.judge_scores is None, "judge never ran: deterministic failure"


@pytest.mark.asyncio
async def test_judge_agreement_gate_raises_below_threshold():
    class AlwaysPass(FakeProvider):
        async def complete_structured(self, prompt, response_model, **kwargs):
            return response_model.model_validate_json(
                json.dumps({"correctness": 1.0, "completeness": 1.0, "format": 1.0})
            )

    samples = [
        {"instruction": "i", "response": "r", "human_pass": False},
        {"instruction": "i", "response": "r", "human_pass": True},
    ]
    with pytest.raises(ValueError, match="below required"):
        await judge_agreement(AlwaysPass(), samples, threshold=0.8)


@pytest.mark.asyncio
async def test_run_config_produces_summary_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr("evals.run.RESULTS_DIR", tmp_path)
    monkeypatch.setattr("evals.report.RESULTS_DIR", tmp_path)
    tasks = build_task_set()[:5]
    provider = FakeProvider()

    summary = await run_config("full", repeat=0, provider=provider, tasks=tasks)
    assert summary["tasks"] == 5
    assert (tmp_path / "full-r0.json").exists()

    # A second config for spread math.
    await run_config("no-reviewer", repeat=0, provider=provider, tasks=tasks)

    report = generate_report(results_dir=tmp_path, output=tmp_path / "results.md")
    assert "| full |" in report
    assert "Pass rate" in report


@pytest.mark.asyncio
async def test_cached_provider_roundtrips_structured_output():
    class Counting(FakeProvider):
        calls = 0

        async def complete(self, prompt, **kwargs):
            Counting.calls += 1
            return await super().complete(prompt, **kwargs)

    inner = Counting()
    cache = LLMCache()
    provider = CachedProvider(inner, cache)

    first = await provider.complete("hello cache")
    second = await provider.complete("hello cache")
    assert first.content == second.content
    assert inner.calls == 1, "second identical call must come from cache"
    assert cache.hits == 1 and cache.misses == 1

    key = cache_key("m", "r", "p")
    assert len(key) == 64
