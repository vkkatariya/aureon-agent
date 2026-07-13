import os
import glob
from .base import WorkspaceBoundTool
from .log import log_tool_usage
from .confirm import confirm_with_captain

# Binary extensions to reject
BINARY_EXTS = {".png", ".jpg", ".jpeg", ".pdf", ".exe", ".so", ".zip", ".tar", ".gz", ".bin"}

class FileTool(WorkspaceBoundTool):
    
    @classmethod
    def read_file(cls, path: str, max_lines: int = 500) -> str:
        is_valid, err = cls.validate_path(path, for_write=False)
        if not is_valid:
            log_tool_usage("read_file", {"path": path}, err, "error")
            return f"Error: {err}"
            
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            if len(lines) > max_lines:
                content = "".join(lines[:max_lines])
                content += f"\n...[TRUNCATED to {max_lines} lines]..."
            else:
                content = "".join(lines)
                
            log_tool_usage("read_file", {"path": path, "max_lines": max_lines}, f"Read {len(lines)} lines", "success")
            return content
        except UnicodeDecodeError:
            err = "File is not valid UTF-8 text."
            log_tool_usage("read_file", {"path": path}, err, "error")
            return f"Error: {err}"
        except Exception as e:
            log_tool_usage("read_file", {"path": path}, str(e), "error")
            return f"Error reading file: {e}"

    @classmethod
    async def write_file(cls, context: dict, path: str, content: str) -> str:
        is_valid, err = cls.validate_path(path, for_write=True)
        if not is_valid:
            log_tool_usage("write_file", {"path": path}, err, "error")
            return f"Error: {err}"
            
        _, ext = os.path.splitext(path)
        if ext.lower() in BINARY_EXTS:
            err = f"Writing to binary file extensions ({ext}) is rejected."
            log_tool_usage("write_file", {"path": path}, err, "error")
            return f"Error: {err}"
            
        # Check overwrite
        if os.path.exists(path):
            confirm_text = f"Agent wants to overwrite the existing file: `{path}`\n\nIs this allowed?"
            confirmed = await confirm_with_captain(context, confirm_text)
            if not confirmed:
                log_tool_usage("write_file", {"path": path}, "Overwrite denied", "deny")
                return "Error: File overwrite denied by Captain."
                
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            log_tool_usage("write_file", {"path": path}, "Wrote successfully", "success")
            return "File written successfully."
        except Exception as e:
            log_tool_usage("write_file", {"path": path}, str(e), "error")
            return f"Error writing file: {e}"

    @classmethod
    def list_dir(cls, path: str, pattern: str = "*") -> str:
        is_valid, err = cls.validate_path(path, for_write=False)
        if not is_valid:
            log_tool_usage("list_dir", {"path": path}, err, "error")
            return f"Error: {err}"
            
        try:
            if not os.path.isdir(path):
                return f"Error: {path} is not a directory."
                
            search_path = os.path.join(path, pattern)
            # Use glob to find matches
            matches = glob.glob(search_path)
            
            result = []
            for m in matches[:100]: # limit to 100 entries to prevent spam
                name = os.path.basename(m)
                if os.path.isdir(m):
                    result.append(f"{name}/")
                else:
                    result.append(name)
                    
            res_str = "\n".join(sorted(result))
            if len(matches) > 100:
                res_str += f"\n...and {len(matches) - 100} more items."
                
            log_tool_usage("list_dir", {"path": path, "pattern": pattern}, f"Listed {len(matches)} items", "success")
            return res_str
        except Exception as e:
            log_tool_usage("list_dir", {"path": path}, str(e), "error")
            return f"Error listing directory: {e}"
