import os
import shutil
import uuid
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class Sandbox:
    def __init__(self, source_dir: str):
        self.source_dir = os.path.abspath(source_dir)
        self.id = uuid.uuid4().hex[:8]
        self.temp_dir = f"/tmp/aureon-subagent-{self.id}"
        
    def setup(self):
        os.makedirs(self.temp_dir, exist_ok=True)
        # Instead of complex bwrap which breaks Node/Python environments without full system mounts,
        # we copy the workspace into the temp dir so the subagent can edit freely.
        # We ignore large/virtual directories to speed up copy.
        ignore_patterns = shutil.ignore_patterns('.git', '.venv', 'node_modules', '__pycache__')
        
        # We copy into a 'workspace' subfolder
        self.workspace_copy = os.path.join(self.temp_dir, "workspace")
        shutil.copytree(self.source_dir, self.workspace_copy, ignore=ignore_patterns)
        
        return self.workspace_copy
        
    def cleanup(self):
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            logger.error(f"Failed to cleanup sandbox {self.temp_dir}: {e}")
            
    def get_diff(self) -> str:
        """Returns the diff of files modified by the subagent in the sandbox."""
        # Using git diff if possible, or diff command
        import subprocess
        try:
            # Simple diff between original and copy
            res = subprocess.run(
                ["diff", "-ur", "--exclude=.git", "--exclude=.venv", "--exclude=__pycache__", 
                 self.source_dir, self.workspace_copy],
                capture_output=True, text=True
            )
            # diff returns 1 if there are differences, 0 if same, 2 if error
            if res.returncode in (0, 1):
                return res.stdout
            return f"Error computing diff: {res.stderr}"
        except Exception as e:
            return f"Error computing diff: {e}"
