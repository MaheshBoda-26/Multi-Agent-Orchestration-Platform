"""Judge validation (Task 33): sample file integrity and report shape."""
import json
from pathlib import Path

import pytest

from evals.validate_judge import AGREEMENT_THRESHOLD, load_samples, validate
from llm.fake import FakeProvider

REAL_SAMPLES = load_samples()


def test_sample_file_has_20_balanced_labeled_samples_across_families():
    assert len(REAL_SAMPLES) == 20
    labels = [s["human_pass"] for s in REAL_SAMPLES]
    assert labels.count(True) == 10 and labels.count(False) == 10
    families = {s["family"] for s in REAL_SAMPLES}
    assert families == {"research", "data_analysis", "writing", "coding"}
    # Every family carries both labels, so agreement is not family-trivial.
    for family in families:
        fam_labels = [s["human_pass"] for s in REAL_SAMPLES if s["family"] == family]
        assert True in fam_labels and False in fam_labels
    assert len({s["id"] for s in REAL_SAMPLES}) == 20


def test_load_samples_rejects_missing_fields(tmp_path):
    bad = tmp_path / "samples.jsonl"
    bad.write_text(json.dumps({"id": "x", "instruction": "i", "response": "r"}) + "\n")
    with pytest.raises(ValueError, match="missing fields"):
        load_samples(bad)


def test_load_samples_rejects_duplicates_and_nonbool_labels(tmp_path):
    dup = tmp_path / "dup.jsonl"
    line = json.dumps({"id": "a", "instruction": "i", "response": "r", "human_pass": True})
    dup.write_text(line + "\n" + line + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_samples(dup)

    nonbool = tmp_path / "nb.jsonl"
    nonbool.write_text(
        json.dumps({"id": "a", "instruction": "i", "response": "r", "human_pass": "yes"}) + "\n"
    )
    with pytest.raises(ValueError, match="boolean"):
        load_samples(nonbool)


@pytest.mark.asyncio
async def test_validate_report_shape_with_perfect_judge():
    class PerfectJudge(FakeProvider):
        """Judge scores everything 1.0: agrees with all human_pass=True rows."""

        async def complete_structured(self, prompt, response_model, **kwargs):
            return response_model.model_validate_json(
                json.dumps({"correctness": 1.0, "completeness": 1.0, "format": 1.0})
            )

    pass_samples = [s for s in REAL_SAMPLES if s["human_pass"]]
    report = await validate(PerfectJudge(), pass_samples)
    assert report["agreement"] == 1.0
    assert report["gate_passed"] is True
    assert report["threshold"] == 0.8
    assert report["disagreements"] == []
    assert set(report["per_family"]) == {"research", "data_analysis", "writing", "coding"}


@pytest.mark.asyncio
async def test_validate_counts_disagreements_and_never_gates_automatically():
    class NeverPassJudge(FakeProvider):
        """Judge scores everything 0.1: disagrees with every positive label."""

        async def complete_structured(self, prompt, response_model, **kwargs):
            return response_model.model_validate_json(
                json.dumps({"correctness": 0.1, "completeness": 0.1, "format": 0.1})
            )

    report = await validate(NeverPassJudge(), REAL_SAMPLES)
    # 10 negative labels agree (judge says fail, human says fail);
    # 10 positive labels disagree.
    assert report["agreements"] == 10
    assert report["agreement"] == pytest.approx(0.5)
    assert report["gate_passed"] is False, "gating stays with the caller/CLI"
    assert len(report["disagreements"]) == 10


def test_threshold_is_the_published_gate():
    assert AGREEMENT_THRESHOLD == 0.8
