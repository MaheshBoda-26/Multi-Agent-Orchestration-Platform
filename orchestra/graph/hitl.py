"""Human-in-the-loop policy.

The four levels and their trigger mapping live in config/escalation.yaml; this
module exposes them to the graph and builds the interrupt payload shape. The
actual interrupt() calls live in graph/approval_nodes.py, in dedicated nodes.
"""
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel

from graph.escalation import load_escalation

_config = load_escalation()


class EscalationLevel(BaseModel):
    """Defines one of the four escalation levels for human-in-the-loop."""

    level: Literal["notify", "approve_action", "approve_plan", "take_over"]
    description: str
    requires_response: bool = True


ESCALATION_LEVELS: Dict[str, EscalationLevel] = {
    key: EscalationLevel(
        level=key,  # type: ignore[arg-type]
        description=level.description,
        requires_response=level.requires_response,
    )
    for key, level in _config.levels.items()
}

ESCALATION_TRIGGERS: Dict[str, str] = dict(_config.triggers)


class HITLManager:
    """Builds the packaged context a human needs to decide."""

    def should_escalate(self, trigger: str) -> str:
        return ESCALATION_TRIGGERS.get(trigger, "notify")

    def create_interrupt_payload(
        self,
        task_id: str,
        trigger: str,
        context: Dict[str, Any],
        proposed_action: Optional[str] = None,
    ) -> Dict[str, Any]:
        level = self.should_escalate(trigger)
        escalation = ESCALATION_LEVELS[level]
        return {
            "task_id": task_id,
            "escalation_level": level,
            "trigger": trigger,
            "description": escalation.description,
            "context": context,
            "proposed_action": proposed_action,
            "requires_response": escalation.requires_response,
        }


# Global HITL manager
hitl_manager = HITLManager()
