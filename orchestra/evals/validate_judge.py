"""Judge validation against hand-labeled samples (Task 33).

Runs `judge_agreement` from graders.py over `evals/judge_samples.jsonl` and
writes evals/output/judge_agreement.json. The gate: agreement >= 0.8 with a
human. Fake-provider runs are for plumbing only (they score ~50-60% because
the fake judge is not a judge); pass --provider openrouter for the real number.

Usage:
    OPENROUTER_API_KEY=... uv run python -m evals.validate_judge --provider openrouter
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from evals.graders import judge_agreement
from llm.factory import build_provider
from llm.routing import load_routing

SAMPLES_PATH = Path(__file__).resolve().parent / "judge_samples.jsonl"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
AGREEMENT_THRESHOLD = 0.8


def load_samples(path: Path = SAMPLES_PATH) -> List[Dict[str, Any]]:
    """Load the hand-labeled samples; every line must carry all four fields."""
    samples: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        sample = json.loads(line)
        missing = {"id", "instruction", "response", "human_pass"} - set(sample)
        if missing:
            raise ValueError(f"{path.name}: sample missing fields {sorted(missing)}")
        if sample["id"] in seen_ids:
            raise ValueError(f"{path.name}: duplicate sample id {sample['id']!r}")
        seen_ids.add(sample["id"])
        if not isinstance(sample["human_pass"], bool):
            raise ValueError(f"{sample['id']}: human_pass must be a boolean")
        samples.append(sample)
    if len(samples) < 20:
        raise ValueError(f"expected 20 hand-labeled samples, found {len(samples)}")
    return samples


async def validate(provider: Any, samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Score every sample with the judge and report agreement per family."""
    agreements = 0
    per_family: Dict[str, Dict[str, int]] = {}
    disagreements: List[Dict[str, Any]] = []
    for sample in samples:
        result = await LLMJudgeGrader_safe(provider, sample)
        matched = result["judge_pass"] == sample["human_pass"]
        if matched:
            agreements += 1
        else:
            disagreements.append({
                "id": sample["id"],
                "human_pass": sample["human_pass"],
                "judge_overall": result["overall"],
            })
        family = sample.get("family", "unknown")
        stats = per_family.setdefault(family, {"total": 0, "agreed": 0})
        stats["total"] += 1
        stats["agreed"] += 1 if matched else 0

    agreement = agreements / len(samples)
    return {
        "provider": type(getattr(provider, "_inner", provider)).__name__,
        "judge_model": load_routing().model_for("judge"),
        "samples": len(samples),
        "agreements": agreements,
        "agreement": round(agreement, 4),
        "threshold": AGREEMENT_THRESHOLD,
        "gate_passed": agreement >= AGREEMENT_THRESHOLD,
        "per_family": per_family,
        "disagreements": disagreements,
    }


async def LLMJudgeGrader_safe(provider: Any, sample: Dict[str, Any]) -> Dict[str, Any]:
    """One judge call: (judge_pass, overall). Judge crashes count as a miss."""
    from evals.graders import LLMJudgeGrader

    try:
        result = await LLMJudgeGrader(provider, [], 1).grade(
            "validation", sample["instruction"], sample["response"]
        )
        overall = float(result.judge_scores.overall()) if result.judge_scores else 0.0
        return {"judge_pass": bool(result.passed), "overall": overall}
    except Exception:  # noqa: BLE001 - a judge failure is a validation signal
        return {"judge_pass": False, "overall": 0.0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validate the LLM judge")
    parser.add_argument("--provider", choices=["fake", "openrouter"], default=None)
    args = parser.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    samples = load_samples()
    provider = build_provider()
    try:
        report = asyncio.run(validate(provider, samples))
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_DIR / "judge_agreement.json"
    out.write_text(json.dumps(report, indent=2))
    status = "PASS" if report["gate_passed"] else "FAIL"
    print(
        f"{status}: judge agreement {report['agreement']:.2f} "
        f"({report['agreements']}/{report['samples']}) vs threshold "
        f"{report['threshold']:.2f}; model {report['judge_model']}"
    )
    print(f"report written to {out}")
    if not report["gate_passed"]:
        sys.exit(1)
