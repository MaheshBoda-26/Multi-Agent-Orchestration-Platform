import logging
from typing import Dict, Set

logger = logging.getLogger(__name__)


class PermissionManager:
    """Manages tool access permissions for different specialists."""

    def __init__(self) -> None:
        # specialist_name -> set of tool_names
        self._permissions: Dict[str, Set[str]] = {}
        # Sensitive tools that require human approval
        self._sensitive_tools: Set[str] = set()

    def grant(self, specialist: str, tool_name: str) -> None:
        if specialist not in self._permissions:
            self._permissions[specialist] = set()
        self._permissions[specialist].add(tool_name)
        logger.info("Granted %s to %s", tool_name, specialist)

    def revoke(self, specialist: str, tool_name: str) -> None:
        if specialist in self._permissions:
            self._permissions[specialist].discard(tool_name)
            logger.info("Revoked %s from %s", tool_name, specialist)

    def has_permission(self, specialist: str, tool_name: str) -> bool:
        return tool_name in self._permissions.get(specialist, set())

    def mark_sensitive(self, tool_name: str) -> None:
        """Mark a tool as requiring human approval before execution."""
        self._sensitive_tools.add(tool_name)
        logger.info("Marked %s as sensitive (requires approval)", tool_name)

    def is_sensitive(self, tool_name: str) -> bool:
        return tool_name in self._sensitive_tools


# Global permission manager
permission_manager = PermissionManager()
