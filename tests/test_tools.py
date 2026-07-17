import os
from aureon_agent.tools.base import WorkspaceBoundTool
from aureon_agent.tools.terminal import is_auto_run, is_destructive

def test_workspace_bound_tool_validation():
    rw_dir = WorkspaceBoundTool.ALLOWED_RW
    ro_dir = WorkspaceBoundTool.ALLOWED_RO
    
    # Read allowed
    assert WorkspaceBoundTool.validate_path(os.path.join(rw_dir, "test.txt"), for_write=False)[0]
    assert WorkspaceBoundTool.validate_path(os.path.join(ro_dir, "test.txt"), for_write=False)[0]
    
    # Write allowed only in RW
    assert WorkspaceBoundTool.validate_path(os.path.join(rw_dir, "test.txt"), for_write=True)[0]
    assert not WorkspaceBoundTool.validate_path(os.path.join(ro_dir, "test.txt"), for_write=True)[0]
    
    # Outside paths rejected
    assert not WorkspaceBoundTool.validate_path("/etc/passwd", for_write=False)[0]
    assert not WorkspaceBoundTool.validate_path("/tmp/test", for_write=True)[0]

def test_terminal_allowlist():
    assert is_auto_run(["ls", "-la"])
    assert is_auto_run(["cat", "file.txt"])
    assert is_auto_run(["git", "status"])
    
    assert not is_auto_run(["rm", "-rf", "/"])
    assert not is_auto_run(["curl", "http://example.com"])

def test_terminal_destructive():
    assert is_destructive(["rm", "-rf", "/"])
    assert is_destructive(["mv", "a", "b"])
    assert is_destructive(["echo", "hello", ">", "file.txt"])
    assert is_destructive(["systemctl", "stop", "service"])
    
    assert not is_destructive(["ls", "-la"])
    assert not is_destructive(["git", "status"])
