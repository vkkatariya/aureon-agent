import os
import pytest
from aureon_agent.tools.todo import TodoTool
from aureon_agent.tools.base import WorkspaceBoundTool

def test_todo_tool_validation():
    # Write only allowed in RW, must end in .md, cannot be in RO
    rw_dir = WorkspaceBoundTool.ALLOWED_RW
    ro_dir = WorkspaceBoundTool.ALLOWED_RO
    
    assert TodoTool._validate_todo_path(os.path.join(rw_dir, "test.md"))[0] == True
    assert TodoTool._validate_todo_path(os.path.join(rw_dir, "test.txt"))[0] == False
    assert TodoTool._validate_todo_path(os.path.join(ro_dir, "test.md"))[0] == False
    assert TodoTool._validate_todo_path("/tmp/test.md")[0] == False

def test_todo_tool_methods(tmp_path):
    # Mock ALLOWED_RW to be tmp_path for test
    original_rw = WorkspaceBoundTool.ALLOWED_RW
    WorkspaceBoundTool.ALLOWED_RW = str(tmp_path)
    
    try:
        test_file = os.path.join(tmp_path, "todo.md")
        
        # Test add
        TodoTool.todo_add(test_file, "First task")
        content = TodoTool.todo_read(test_file)
        assert "- [ ] First task" in content
        
        # Test add second
        TodoTool.todo_add(test_file, "Second task")
        content = TodoTool.todo_read(test_file)
        assert "- [ ] First task\n- [ ] Second task" in content
        
        # Test overwrite
        TodoTool.todo_write(test_file, "New plan")
        content = TodoTool.todo_read(test_file)
        assert content == "New plan"
        
        # Test append
        TodoTool.todo_write(test_file, "Appended part", append=True)
        content = TodoTool.todo_read(test_file)
        assert "New plan\nAppended part" in content
        
    finally:
        WorkspaceBoundTool.ALLOWED_RW = original_rw
