import logging
from typing import Set, Dict
from .registry import ToolSchema

logger = logging.getLogger(__name__)

class PermissionManager:
    """Manages tool access permissions for different specialists."""
    
    def __init__(self):
        # specialist_name -> set of tool_names
        self._permissions: Dict[str, Set[str]] = {}

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

# Global permission manager
permission_manager = PermissionManager()
