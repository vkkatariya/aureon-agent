import os
from typing import Tuple

class WorkspaceBoundTool:
    ALLOWED_RW = os.path.expanduser("~/dev-shared/projects/")
    ALLOWED_RO = os.path.expanduser("~/.openclaw/workspace/")

    @classmethod
    def validate_path(cls, path: str, for_write: bool = False) -> Tuple[bool, str]:
        """
        Validates if a path is within the allowed workspaces.
        Returns (is_valid, error_message).
        No symlink following outside allowlist.
        """
        try:
            # Resolve the path to its absolute form, resolving symlinks
            abs_path = os.path.realpath(os.path.expanduser(path))
        except Exception as e:
            return False, f"Path resolution error: {e}"

        # Check write permissions
        if for_write:
            if not abs_path.startswith(cls.ALLOWED_RW):
                return False, f"Path '{path}' is not within the writable allowlist ({cls.ALLOWED_RW})"
        else:
            # For read, it can be in RW or RO
            if not (abs_path.startswith(cls.ALLOWED_RW) or abs_path.startswith(cls.ALLOWED_RO)):
                return False, f"Path '{path}' is not within the readable allowlist ({cls.ALLOWED_RW} or {cls.ALLOWED_RO})"

        return True, ""
