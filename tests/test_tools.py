import os
import pytest
from aureon_agent.tools.base import WorkspaceBoundTool
from aureon_agent.tools.terminal import is_auto_run, is_destructive

def test_workspace_bound_tool_validation():
    rw_dir = WorkspaceBoundTool.ALLOWED_RW
    ro_dir = WorkspaceBoundTool.ALLOWED_RO
    
    # Read allowed
    assert WorkspaceBoundTool.validate_path(os.path.join(rw_dir, "test.txt"), for_write=False)[0] == True
    assert WorkspaceBoundTool.validate_path(os.path.join(ro_dir, "test.txt"), for_write=False)[0] == True
    
    # Write allowed only in RW
    assert WorkspaceBoundTool.validate_path(os.path.join(rw_dir, "test.txt"), for_write=True)[0] == True
    assert WorkspaceBoundTool.validate_path(os.path.join(ro_dir, "test.txt"), for_write=True)[0] == False
    
    # Outside paths rejected
    assert WorkspaceBoundTool.validate_path("/etc/passwd", for_write=False)[0] == False
    assert WorkspaceBoundTool.validate_path("/tmp/test", for_write=True)[0] == False

def test_terminal_allowlist():
    assert is_auto_run(["ls", "-la"]) == True
    assert is_auto_run(["cat", "file.txt"]) == True
    assert is_auto_run(["git", "status"]) == True
    
    assert is_auto_run(["rm", "-rf", "/"]) == False
    assert is_auto_run(["curl", "http://example.com"]) == False

def test_terminal_destructive():
    assert is_destructive(["rm", "-rf", "/"]) == True
    assert is_destructive(["mv", "a", "b"]) == True
    assert is_destructive(["echo", "hello", ">", "file.txt"]) == True
    assert is_destructive(["systemctl", "stop", "service"]) == True
    
    assert is_destructive(["ls", "-la"]) == False
    assert is_destructive(["git", "status"]) == False
