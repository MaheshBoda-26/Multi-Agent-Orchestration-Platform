"""Escalation policy loader: config/escalation.yaml is the source of truth."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "escalation.yaml"


@dataclass
class EscalationLevel:
    key: str
    description: str
    requires_response: bool = True


@dataclass
class EscalationConfig:
    levels: Dict[str, EscalationLevel] = field(default_factory=dict)
    triggers: Dict[str, str] = field(default_factory=dict)
    # None means "no timeout": approvals wait indefinitely.
    approval_timeout_seconds: Optional[int] = None

    def level_for(self, trigger: str) -> EscalationLevel:
        key = self.triggers.get(trigger, "notify")
        return self.levels[key]


def load_escalation(path: Optional[Path] = None) -> EscalationConfig:
    data = yaml.safe_load((path or DEFAULT_PATH).read_text(encoding="utf-8")) or {}
    levels = {
        key: EscalationLevel(
            key=key,
            description=str(value.get("description", "")),
            requires_response=bool(value.get("requires_response", True)),
        )
        for key, value in (data.get("levels") or {}).items()
    }
    return EscalationConfig(
        levels=levels,
        triggers={str(k): str(v) for k, v in (data.get("triggers") or {}).items()},
        approval_timeout_seconds=data.get("approval_timeout_seconds"),
    )
