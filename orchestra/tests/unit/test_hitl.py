import pytest
from graph.hitl import HITLManager, ESCALATION_TRIGGERS, ESCALATION_LEVELS
from tools.permissions import permission_manager

def test_escalation_triggers_mapping():
    assert ESCALATION_TRIGGERS["low_confidence_plan"] == "approve_plan"
    assert ESCALATION_TRIGGERS["sensitive_tool_requested"] == "approve_action"
    assert ESCALATION_TRIGGERS["second_failure"] == "approve_action"
    assert ESCALATION_TRIGGERS["reviewer_escalate"] == "approve_action"
    assert ESCALATION_TRIGGERS["user_requested"] == "take_over"

def test_escalation_levels():
    assert "notify" in ESCALATION_LEVELS
    assert "approve_action" in ESCALATION_LEVELS
    assert "approve_plan" in ESCALATION_LEVELS
    assert "take_over" in ESCALATION_LEVELS
    
    notify = ESCALATION_LEVELS["notify"]
    assert notify.requires_response == False
    
    approve = ESCALATION_LEVELS["approve_action"]
    assert approve.requires_response == True

def test_hitl_manager_payload():
    manager = HITLManager()
    payload = manager.create_interrupt_payload(
        task_id="test-123",
        trigger="sensitive_tool_requested",
        context={"completed_steps": ["step1"]},
        proposed_action="Delete file"
    )
    
    assert payload["task_id"] == "test-123"
    assert payload["escalation_level"] == "approve_action"
    assert payload["trigger"] == "sensitive_tool_requested"
    assert payload["proposed_action"] == "Delete file"
    assert payload["requires_response"] == True

def test_permission_manager_sensitive_tools():
    # Reset for test
    permission_manager._sensitive_tools.clear()
    
    permission_manager.mark_sensitive("file_write")
    assert permission_manager.is_sensitive("file_write") == True
    assert permission_manager.is_sensitive("file_read") == False
    
    permission_manager.mark_sensitive("http_get")
    assert permission_manager.is_sensitive("http_get") == True
