"""Model routing: the only place model names and prices live."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "routing.yaml"


@dataclass
class Routing:
    default: str
    roles: Dict[str, str] = field(default_factory=dict)
    costs: Dict[str, Tuple[float, float]] = field(default_factory=dict)

    def model_for(self, role: Optional[str]) -> str:
        if role:
            return self.roles.get(role, self.default)
        return self.default

    def costs_for(self, model: str) -> Tuple[float, float]:
        return self.costs.get(model, self.costs.get("default", (0.0, 0.0)))


def load_routing(path: Optional[Path] = None) -> Routing:
    source = path or DEFAULT_PATH
    data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    costs = {
        key: (float(value[0]), float(value[1]))
        for key, value in (data.get("costs") or {}).items()
    }
    return Routing(
        default=str(data.get("default", "")),
        roles={str(k): str(v) for k, v in (data.get("roles") or {}).items()},
        costs=costs,
    )
