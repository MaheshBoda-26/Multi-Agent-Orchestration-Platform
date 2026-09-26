"""Injection-suite report (Task 40): before/after markdown from runner JSON.

Reads ``security/output/injection-undefended.json`` and
``security/output/injection-defended.json`` (written by ``security.run_injection``)
and renders ``security/results.md`` with per-class pass rates, so the published
numbers always trace to runner output instead of prose.
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
REPORT_PATH = Path(__file__).resolve().parent / "results.md"

_CLASS_LABELS = {
    "direct_instruction": "Direct instruction",
    "data_framing": "Data framing",
    "exfiltration": "Exfiltration",
    "privilege_escalation": "Privilege escalation",
}


def _load(mode: str, results_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    path = (results_dir or OUTPUT_DIR) / f"injection-{mode}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def generate_report(
    results_dir: Optional[Path] = None,
    output: Optional[Path] = None,
) -> str:
    """Render the before/after markdown table.

    Missing results render as "not run" rows so the report still generates on a
    clean checkout; run `python -m security.run_injection` to fill them in.
    """
    undefended = _load("undefended", results_dir)
    defended = _load("defended", results_dir)

    lines = [
        "# Prompt-injection suite results",
        "",
        "25 cases in 4 classes, delivered as tool output. A case passes when the",
        "agent satisfies its expected_behavior (ignore / surface / no_disclosure).",
        "",
        "| Suite | Cases | Passed | Pass rate |",
        "|---|---|---|---|",
    ]
    for label, data in (("Undefended", undefended), ("Defended", defended)):
        if data is None:
            lines.append(f"| {label} | - | - | not run |")
            continue
        lines.append(
            f"| {label} | {data['cases']} | {data['passed']} | {data['pass_rate']:.0%} |"
        )

    lines += [
        "",
        "## Per-class pass rates",
        "",
        "| Class | Undefended | Defended |",
        "|---|---|---|",
    ]
    classes = sorted(
        set(_CLASS_LABELS)
        | set((undefended or {}).get("by_class", {}))
        | set((defended or {}).get("by_class", {}))
    )
    for klass in classes:
        label = _CLASS_LABELS.get(klass, klass)
        cells = [label]
        for data in (undefended, defended):
            stats = (data or {}).get("by_class", {}).get(klass)
            if stats is None:
                cells.append("-")
            else:
                cells.append(f"{stats['passed']}/{stats['total']}")
        lines.append("| " + " | ".join(cells) + " |")

    if undefended and defended:
        delta = defended["pass_rate"] - undefended["pass_rate"]
        lines += [
            "",
            f"Defense effect: **{delta:+.0%}** pass rate (fake-provider baseline: the",
            "undefended stand-in obeys injected commands, the defended run refuses",
            "framed instructions). Live OpenRouter numbers land here when the suite",
            "is run with `--provider openrouter`.",
        ]

    report = "\n".join(lines) + "\n"
    output = output or REPORT_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    return report


if __name__ == "__main__":
    print(generate_report())
