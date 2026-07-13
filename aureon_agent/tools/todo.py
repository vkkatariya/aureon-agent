import os
from .base import WorkspaceBoundTool
from .log import log_tool_usage

class TodoTool(WorkspaceBoundTool):
    @classmethod
    def _validate_todo_path(cls, path: str) -> tuple[bool, str]:
        # Only allow dev-shared/projects, no ~/.openclaw
        is_valid, err = cls.validate_path(path, for_write=True)
        if not is_valid:
            return False, err
        abs_path = os.path.realpath(os.path.expanduser(path))
        if abs_path.startswith(cls.ALLOWED_RO):
            return False, "Cannot write todo files to read-only workspace."
        if not abs_path.endswith(".md"):
            return False, "Todo files must be Markdown (.md) format."
        return True, ""

    @classmethod
    def todo_read(cls, path: str = "tasks/todo.md") -> str:
        # Resolving relative to current working directory (the project root)
        abs_path = os.path.abspath(path)
        is_valid, err = cls._validate_todo_path(abs_path)
        # Read can be allowed from RO if we want, but instructions say path validation: `~/dev-shared/projects/` only
        if not is_valid:
            log_tool_usage("todo_read", {"path": path}, err, "error")
            return f"Error: {err}"
            
        try:
            if not os.path.exists(abs_path):
                return "Todo file does not exist yet."
            with open(abs_path, "r", encoding="utf-8") as f:
                content = f.read()
            log_tool_usage("todo_read", {"path": path}, "Read successfully", "success")
            return content
        except Exception as e:
            log_tool_usage("todo_read", {"path": path}, str(e), "error")
            return f"Error reading todo: {e}"

    @classmethod
    def todo_write(cls, path: str, content: str, append: bool = False) -> str:
        abs_path = os.path.abspath(path)
        is_valid, err = cls._validate_todo_path(abs_path)
        if not is_valid:
            log_tool_usage("todo_write", {"path": path, "append": append}, err, "error")
            return f"Error: {err}"
            
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            mode = "a" if append else "w"
            # Ensure it ends with newline if appending
            if append and content and not content.startswith("\n"):
                content = "\n" + content
                
            with open(abs_path, mode, encoding="utf-8") as f:
                f.write(content)
            
            action = "Appended" if append else "Overwrote"
            log_tool_usage("todo_write", {"path": path, "append": append}, f"{action} successfully", "success")
            return f"Successfully {action.lower()} todo file."
        except Exception as e:
            log_tool_usage("todo_write", {"path": path, "append": append}, str(e), "error")
            return f"Error writing todo: {e}"

    @classmethod
    def todo_add(cls, path: str, item: str) -> str:
        abs_path = os.path.abspath(path)
        is_valid, err = cls._validate_todo_path(abs_path)
        if not is_valid:
            log_tool_usage("todo_add", {"path": path}, err, "error")
            return f"Error: {err}"
            
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            # Ensure file ends with newline if it exists
            prefix = ""
            if os.path.exists(abs_path):
                with open(abs_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if content and not content.endswith("\n"):
                    prefix = "\n"
                    
            item_line = f"{prefix}- [ ] {item}\n"
            
            with open(abs_path, "a", encoding="utf-8") as f:
                f.write(item_line)
                
            log_tool_usage("todo_add", {"path": path}, "Added item successfully", "success")
            return "Item added successfully."
        except Exception as e:
            log_tool_usage("todo_add", {"path": path}, str(e), "error")
            return f"Error adding todo item: {e}"
