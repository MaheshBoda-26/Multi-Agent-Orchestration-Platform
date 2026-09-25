import logging
from typing import Set, Dict
from .registry import ToolSchema

logger = logging.getLogger(__name__)

class PermissionManager:
    """Manages tool access permissions for different specialists."""
    
    def __init__(self):
        # specialist_name -> set of tool_names
        self._permissions: Dict[str, Set[str]] = {}
        # Sensitive tools that require human approval
        self._sensitive_tools: Set[str] = set()

    def grant(self, specialist: str, tool_name: str):
        if specialist not in self._permissions:
            self._permissions[specialist] = set()
        self._permissions[specialist].add(tool_name)
        logger.info(f"Granted {tool_name} to {specialist}")

    def revoke(self, specialist: str, tool_name: str):
        if specialist in self._permissions:
            self._permissions[specialist].discard(tool_name)
            logger.info(f"Revoked {tool_name} from {specialist}")

    def has_permission(self, specialist: str, tool_name: str) -> bool:
        return tool_name in self._permissions.get(specialist, set())

    def mark_sensitive(self, tool_name: str):
        """Mark a tool as requiring human approval before execution."""
        self._sensitive_tools.add(tool_name)
        logger.info(f"Marked {tool_name} as sensitive (requires approval)")

    def is_sensitive(self, tool_name: str) -> bool:
        return tool_name in self._sensitive_tools

# Global permission manager
permission_manager = PermissionManager()
