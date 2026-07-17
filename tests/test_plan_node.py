import os
from plan_node import require_plan, count_features

def test_count_features():
    # Scenario 1: 3 imperative verbs -> 3
    assert count_features("build the app, create the db, and fix the bug") >= 3
    
    # Scenario 2: mix of URLs, paths, and verbs -> 3+
    assert count_features("update foo/bar.py and check http://example.com") >= 3
    
    # Scenario 3: read-only bypasses
    assert count_features("show me how to build the app and fix it") == 0
    
    # Scenario 4: less than 3 steps
    assert count_features("just build the app") < 3

def test_require_plan(tmp_path, monkeypatch):
    ws = str(tmp_path)
    
    # Mock the global path so it doesn't read the real one
    def mock_expanduser(path):
        if path == "~/.openclaw/workspace/tasks/todo.md":
            return str(tmp_path / "fake_global_todo.md")
        return path
    monkeypatch.setattr(os.path, "expanduser", mock_expanduser)
    
    # Scenario 5: >3 steps, no plan -> blocked
    ok, reason = require_plan(ws, "build create fix")
    assert not ok
    assert "Plan needed" in reason
    
    # Scenario 6: >3 steps, bypass phrase -> ok
    ok, reason = require_plan(ws, "just do it build create fix")
    assert ok
    assert reason is None
    
    # Scenario 7: <3 steps -> ok
    ok, reason = require_plan(ws, "build the app")
    assert ok
    
    # Scenario 8: >3 steps, plan exists -> ok
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()
    todo_file = tasks_dir / "todo.md"
    todo_file.write_text("- [ ] fix something")
    ok, reason = require_plan(ws, "build create fix")
    assert ok
