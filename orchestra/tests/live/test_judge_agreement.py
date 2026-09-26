"""Live judge agreement (Task 33 gate). Run manually before a phase exit:

    OPENROUTER_API_KEY=... uv run pytest tests/live/test_judge_agreement.py -m live -q
"""
import os

import pytest

from evals.validate_judge import AGREEMENT_THRESHOLD, load_samples, validate
from llm.factory import build_provider

pytestmark = pytest.mark.live


@pytest.mark.asyncio
async def test_judge_agreement_meets_threshold():
    if not os.getenv("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")

    report = await validate(build_provider(), load_samples())
    assert report["gate_passed"], report
    assert report["agreement"] >= AGREEMENT_THRESHOLD
