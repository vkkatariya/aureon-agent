import subprocess
import shlex
import os
from .log import log_tool_usage
from .confirm import confirm_with_captain

ALLOWED_AUTO_RUN = {
    "ls", "cat", "grep", "find", "pwd", "echo", "date", "whoami",
    "hostname", "df", "du", "wc", "head", "tail", "which", "env"
}
GIT_ALLOWED = {"status", "log", "diff"}

DESTRUCTIVE_CMDS = {
    "rm", "mv", "chmod", "kill", "pkill", "drop", "delete", "truncate", "dd", "mkfs", "fdisk"
}

def is_destructive(cmd_parts: list) -> bool:
    if not cmd_parts:
        return False
    base_cmd = cmd_parts[0]
    
    # Check basic destructive commands
    if base_cmd in DESTRUCTIVE_CMDS:
        return True
        
    # Check systemctl stop
    if base_cmd == "systemctl" and len(cmd_parts) > 1 and cmd_parts[1] == "stop":
        return True
        
    # Shell redirects are blocked by no shell=True, but just in case
    for part in cmd_parts:
        if ">" in part or ">>" in part:
            return True
            
    return False

def is_auto_run(cmd_parts: list) -> bool:
    if not cmd_parts:
        return False
    base_cmd = cmd_parts[0]
    if base_cmd in ALLOWED_AUTO_RUN:
        return True
    if base_cmd == "git" and len(cmd_parts) > 1 and cmd_parts[1] in GIT_ALLOWED:
        return True
    return False

async def terminal_tool(context: dict, command, timeout: int = 30) -> str:
    """
    Executes a terminal command.
    Accepts command as a list of strings OR a single string (which will be parsed with shlex).
    """
    if command is None or command == "":
        return "Error: Empty command."

    # Accept both list and string. LLMs commonly send string commands.
    if isinstance(command, str):
        try:
            command = shlex.split(command)
        except ValueError as e:
            return f"Error: Could not parse command string: {e}"

    if isinstance(command, dict):
        # Some LLM tool-call shapes wrap command in a dict accidentally
        return f"Error: command must be a list or string, got dict ({list(command.keys())})"

    if not isinstance(command, list):
        return f"Error: command must be a list of strings, got {type(command).__name__}"

    if not command:
        return "Error: Empty command."
        
    # Validation
    destructive = is_destructive(command)
    auto_run = is_auto_run(command)
    
    cmd_str = shlex.join(command)
    
    if destructive or not auto_run:
        # Require confirmation for anything not explicitly auto-run
        confirm_text = f"Agent wants to run a shell command:\n`{cmd_str}`\n\nIs this allowed?"
        confirmed = await confirm_with_captain(context, confirm_text)
        if not confirmed:
            log_tool_usage("terminal", {"command": command, "timeout": timeout}, "Denied by Captain", "deny", "Denied")
            return "Command execution denied by Captain."
        
    # Execute
    try:
        # Expand ~ in path-like arguments (subprocess.run with shell=False doesn't expand)
        expanded_command = []
        for arg in command:
            if isinstance(arg, str) and arg.startswith('~'):
                expanded_command.append(os.path.expanduser(arg))
            else:
                expanded_command.append(arg)
        
        process = subprocess.run(
            expanded_command,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        stdout = process.stdout
        stderr = process.stderr
        exit_code = process.returncode
        
        # Truncate to 50KB
        MAX_LEN = 50 * 1024
        combined_output = ""
        if stdout:
            combined_output += f"STDOUT:\n{stdout}\n"
        if stderr:
            combined_output += f"STDERR:\n{stderr}\n"
            
        if len(combined_output) > MAX_LEN:
            combined_output = combined_output[:MAX_LEN] + "\n...[TRUNCATED to 50KB]..."
            
        result_text = f"Exit Code: {exit_code}\n{combined_output}"
        
        log_tool_usage(
            "terminal",
            {"command": command, "timeout": timeout},
            f"Exit Code: {exit_code}",
            str(exit_code),
            "Confirmed" if (destructive or not auto_run) else "Auto-run"
        )
        return result_text
        
    except subprocess.TimeoutExpired:
        log_tool_usage("terminal", {"command": command, "timeout": timeout}, "Timeout expired", "timeout", "N/A")
        return f"Error: Command timed out after {timeout} seconds."
    except Exception as e:
        log_tool_usage("terminal", {"command": command, "timeout": timeout}, f"Error: {e}", "error", "N/A")
        return f"Error executing command: {e}"
