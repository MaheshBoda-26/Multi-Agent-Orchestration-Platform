"""Build the locked 100-task evaluation set (Task 32).

Four families x 25 tasks, written as JSONL to evals/tasks/task_set.jsonl.
Each task carries: id, family, instruction, the deterministic checks a correct
result must satisfy, and (for the memory experiment) a repeat flag linking the
tasks that share a family so Phase 6 can measure plan-with-memory vs without.

The set is deterministic: the same script always writes byte-identical output,
so eval numbers stay comparable across runs.
"""
from pathlib import Path

from pydantic import BaseModel, Field

TASKS_PATH = Path(__file__).resolve().parent / "tasks" / "task_set.jsonl"


class EvalTask(BaseModel):
    id: str
    family: str
    instruction: str
    # Deterministic graders: every substring must appear (case-insensitive) in
    # the final response, and min_chars must be met. The set ships with empty
    # must_contain and a modest floor; the judge carries quality on live runs.
    must_contain: list[str] = Field(default_factory=list)
    min_chars: int = 30
    # Repeated-family flag: true for the 2nd..nth task of a family, so the
    # memory experiment can compare plans that could use earlier lessons.
    repeats_family: bool = False


FAMILIES: dict[str, list[str]] = {
    "research": [
        "Compare {topic} and write a two-paragraph recommendation.",
        "Summarize the current state of {topic} with three key facts.",
        "Explain the trade-offs of {topic} for a small engineering team.",
        "List the main risks of adopting {topic} and how to mitigate them.",
    ],
    "data_analysis": [
        "Compute descriptive statistics for a dataset about {topic} and interpret them.",
        "Given sales numbers related to {topic}, identify the trend and one anomaly.",
        "Write Python that validates a CSV about {topic} and reports row-level errors.",
        "Estimate the growth rate from quarterly figures about {topic} and cite your math.",
    ],
    "writing": [
        "Draft a release announcement about {topic} in a confident, factual tone.",
        "Rewrite a technical explanation of {topic} for a non-technical audience.",
        "Write a one-page checklist for teams adopting {topic}.",
        "Compose a polite email declining a proposal about {topic} with two reasons.",
    ],
    "coding": [
        "Write a Python function that deduplicates a list of records about {topic}.",
        "Automate a report on {topic}: read input rows and print a summary table.",
        "Fix this buggy snippet that is supposed to sort {topic} entries by date.",
        "Write tests for a module that converts {topic} data between formats.",
    ],
}

TOPICS: list[str] = [
    "vector databases", "retries with backoff", "cache invalidation",
    "feature flags", "API rate limits", "data migrations", "blue-green deploys",
    " observability dashboards", "prompt injection", "SQL query planners",
]


def build_task_set() -> list[EvalTask]:
    """25 tasks per family: 4 templates x 7 topics minus the overflow of the
    last template, so each family lands on exactly 25."""
    tasks: list[EvalTask] = []
    for family, templates in FAMILIES.items():
        count = 0
        for template in templates:
            for topic in TOPICS:
                if count >= 25:
                    break
                count += 1
                tasks.append(EvalTask(
                    id=f"{family}-{count:03d}",
                    family=family,
                    instruction=template.format(topic=topic.strip()),
                    must_contain=_checks_for(family),
                    # Repeats = tasks past the first template round, so the
                    # memory experiment has prior lessons in the same family.
                    repeats_family=count > len(templates) * (len(TOPICS) - 1) or count > 7,
                ))
        assert count == 25, f"family {family} produced {count} tasks"
    return tasks


def _checks_for(family: str) -> list[str]:
    """Family-shaped deterministic checks. Kept deliberately shallow: they
    catch empty/degenerate outputs, while the LLM judge (validated against
    hand labels) carries the quality signal on live runs."""
    return {
        "research": [],
        "data_analysis": [],
        "writing": [],
        "coding": [],
    }.get(family, [])


def write_task_set(path: Path = TASKS_PATH) -> list[EvalTask]:
    tasks = build_task_set()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for task in tasks:
            fh.write(task.model_dump_json() + "\n")
    return tasks


def load_task_set(path: Path = TASKS_PATH) -> list[EvalTask]:
    if not path.exists():
        write_task_set(path)
    return [
        EvalTask.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


if __name__ == "__main__":
    built = write_task_set()
    print(f"Wrote {len(built)} tasks to {TASKS_PATH}")
