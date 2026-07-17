import os
from aureon_agent.subagent.sandbox import Sandbox

def test_subagent_sandbox(tmp_path):
    # Setup test workspace
    test_file = tmp_path / "test.txt"
    test_file.write_text("hello")
    
    # Init sandbox
    sb = Sandbox(str(tmp_path))
    try:
        ws = sb.setup()
        
        assert os.path.exists(ws)
        assert os.path.exists(os.path.join(ws, "test.txt"))
        
        # Test diff
        copy_file = os.path.join(ws, "test.txt")
        with open(copy_file, "w") as f:
            f.write("hello world")
            
        diff = sb.get_diff()
        assert "+hello world" in diff or "hello world" in diff
        assert "-hello" in diff or "hello" in diff
    finally:
        sb.cleanup()
        assert not os.path.exists(sb.temp_dir)
