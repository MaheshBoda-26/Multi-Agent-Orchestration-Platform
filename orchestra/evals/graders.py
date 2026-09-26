"""Graders for the eval harness (Tasks 32-33).

Deterministic checks run first (free, reproducible). The LLM judge scores
outputs the checks cannot capture; its agreement with hand labels is measured
by validate_judge and gated before any live eval trusts it.
"""
import re
from typing import Any, Dict, List, Optional, Protocol

from pydantic import BaseModel, Field

from llm.provider import LLMProvider


class GradeResult(BaseModel):
    task_id: str
    passed: bool
    score: float  # 0..1
    deterministic_passed: bool
    judge_scores: Optional["JudgeScores"] = None
    reason: str = ""
    latency_ms: int = 0


class JudgeScores(BaseModel):
    correctness: float = Field(ge=0, le=1)
    completeness: float = Field(ge=0, le=1)
    format: float = Field(ge=0, le=1)

    def overall(self) -> float:
        return (self.correctness + self.completeness + self.format) / 3.0


class Grader(Protocol):
    async def grade(self, task_id: str, instruction: str, response: str) -> GradeResult: ...


class DeterministicGrader:
    """Substring + length checks derived from the task set."""

    def __init__(self, must_contain: List[str], min_chars: int = 50) -> None:
        self.must_contain = must_contain
        self.min_chars = min_chars

    async def grade(self, task_id: str, instruction: str, response: str) -> GradeResult:
        haystack = response.lower()
        missing = [
            needle for needle in self.must_contain
            if needle.lower() not in haystack
        ]
        too_short = len(response.strip()) < self.min_chars
        passed = not missing and not too_short
        reason_parts = []
        if missing:
            reason_parts.append(f"missing: {missing}")
        if too_short:
            reason_parts.append(f"response shorter than {self.min_chars} chars")
        return GradeResult(
            task_id=task_id,
            passed=passed,
            score=1.0 if passed else (0.5 if not missing else 0.0),
            deterministic_passed=passed,
            reason="; ".join(reason_parts) or "all deterministic checks passed",
        )


class LLMJudgeGrader:
    """Scores with the routed 'judge' role model; deterministic gate first."""

    def __init__(self, llm: LLMProvider, must_contain: List[str], min_chars: int = 50):
        self.deterministic = DeterministicGrader(must_contain, min_chars)
        self.llm = llm

    async def grade(self, task_id: str, instruction: str, response: str) -> GradeResult:
        base = await self.deterministic.grade(task_id, instruction, response)
        if not base.passed:
            # A deterministic failure is a failure regardless of judge opinion.
            return base

        prompt = (
            "You are a strict quality judge for an AI assistant's output.\n\n"
            f"Instruction:\n{instruction}\n\n"
            f"Output to judge:\n{response[:4000]}\n\n"
            "Score correctness (is it factually sound?), completeness (does it "
            "fully address the instruction?) and format (is it well structured?) "
            "each between 0.0 and 1.0. Return JSON."
        )
        scores = await self.llm.complete_structured(prompt, JudgeScores, role="judge")
        overall = scores.overall()
        return GradeResult(
            task_id=task_id,
            passed=overall >= 0.6,
            score=overall,
            deterministic_passed=True,
            judge_scores=scores,
            reason=f"judge overall={overall:.2f}",
        )


async def judge_agreement(
    llm: LLMProvider, samples: List[Dict[str, Any]], threshold: float = 0.8
) -> float:
    """Agreement between the judge and hand labels (Task 33).

    Each sample: {instruction, response, human_pass: bool}. Returns the fraction
    the judge grades the same way a human did; raises ValueError below threshold.
    """
    if not samples:
        raise ValueError("no validation samples provided")
    agreements = 0
    for sample in samples:
        result = await LLMJudgeGrader(llm, [], 1).grade(
            "validation", sample["instruction"], sample["response"]
        )
        if result.passed == sample["human_pass"]:
            agreements += 1
    agreement = agreements / len(samples)
    if agreement < threshold:
        raise ValueError(
            f"judge agreement {agreement:.2f} below required {threshold:.2f}"
        )
    return agreement


def _norm(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_from_text(text: str) -> float:
    """Fallback scalar extractor for judge replies (defensive)."""
    match = re.search(r"([01](?:\.\d+)?)", text)
    return _norm(float(match.group(1))) if match else 0.0
