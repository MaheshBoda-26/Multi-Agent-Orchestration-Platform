"""Live-model plan validity (Phase 2 exit). Run manually before a phase exit:

    OPENROUTER_API_KEY=... uv run pytest tests/live -m live -q
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.live


def test_live_plan_validity_meets_threshold():
    if not os.getenv("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY not set")

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "live_plan_check.py"),
         "--provider", "openrouter", "--limit", "20"],
        capture_output=True, text=True, cwd=ROOT, timeout=1200,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    report = json.loads((ROOT / "evals" / "output" / "plan_validity.json").read_text())
    assert report["count"] == 20
    assert report["rate"] >= 0.95, report
