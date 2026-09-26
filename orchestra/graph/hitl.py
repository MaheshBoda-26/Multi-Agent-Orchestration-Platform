from typing import Dict, Any, Optional, Literal
from pydantic import BaseModel
from langgraph.types import interrupt

# Escalation levels
class EscalationLevel(BaseModel):
    """Defines the four escalation levels for human-in-the-loop."""
    level: Literal["notify", "approve_action", "approve_plan", "take_over"]
    description: str
    requires_response: bool = True

ESCALATION_LEVELS = {
    "notify": EscalationLevel(
        level="notify",
        description="Inform human of progress; no action required",
        requires_response=False
    ),
    "approve_action": EscalationLevel(
        level="approve_action",
        description="Human must approve/reject a specific proposed action",
        requires_response=True
    ),
    "approve_plan": EscalationLevel(
        level="approve_plan",
        description="Human must approve/modify the entire plan",
        requires_response=True
    ),
    "take_over": EscalationLevel(
        level="take_over",
        description="Human takes direct control; agent pauses indefinitely",
        requires_response=True
    ),
}

# Trigger conditions mapping
ESCALATION_TRIGGERS = {
    "low_confidence_plan": "approve_plan",
    "sensitive_tool_requested": "approve_action", 
    "second_failure": "approve_action",
    "reviewer_escalate": "approve_action",
    "user_requested": "take_over",
}

class HITLManager:
    """Manages human-in-the-loop interactions using LangGraph interrupts."""
    
    def __init__(self) -> None:
        pass

    def should_escalate(self, trigger: str) -> str:
        """Map a trigger to an escalation level."""
        return ESCALATION_TRIGGERS.get(trigger, "notify")

    def create_interrupt_payload(self, 
                                  task_id: str,
                                  trigger: str,
                                  context: Dict[str, Any],
                                  proposed_action: Optional[str] = None) -> Dict[str, Any]:
        """Create the payload for a LangGraph interrupt."""
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

    async def pause_for_approval(self, 
                                  state: Dict[str, Any], 
                                  trigger: str,
                                  proposed_action: Optional[str] = None) -> Dict[str, Any]:
        """
        Pause execution using LangGraph's interrupt mechanism.
        This saves the checkpoint and waits for human input.
        """
        task_id = state.get("task_id", "unknown")
        context = {
            "completed_steps": list(state.get("results", {}).keys()),
            "plan": state.get("plan"),
            "shared_context": state.get("shared_context"),
        }
        
        payload = self.create_interrupt_payload(
            task_id=task_id,
            trigger=trigger,
            context=context,
            proposed_action=proposed_action
        )
        
        # This is where LangGraph saves state and yields control
        # The human response will be returned when execution resumes
        human_response = interrupt(payload)
        if not isinstance(human_response, dict):
            return {"action": "unknown", "raw_response": human_response}
        return dict(human_response)

# Global HITL manager
hitl_manager = HITLManager()
