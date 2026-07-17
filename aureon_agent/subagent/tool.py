from .sandbox import Sandbox
from .task import SubagentTask
from .claude_code import ClaudeCodeBackend
from .log import log_subagent_dispatch
import os
import uuid
from aureon_agent.tools.log import log_tool_usage
from aureon_agent.tools.confirm import confirm_with_captain

# Initialize backend instances
BACKENDS = {
    "claude-code": ClaudeCodeBackend()
}

async def delegate_task_tool(context: dict, description: str, backend: str = "claude-code", timeout_sec: int = 300, files_to_inspect: list = None) -> str:
    if os.getenv("AUREON_SUBAGENT_DISABLED") == "1":
        return "Error: Subagents are currently disabled by AUREON_SUBAGENT_DISABLED=1"
        
    if backend not in BACKENDS:
        return f"Error: Unknown backend '{backend}'. Available: {list(BACKENDS.keys())}"
        
    context.get("router")
    context.get("session_id")
    
    # Cost control estimation - normally we would count tokens here. 
    # For now, we will do a rough heuristic based on file sizes or just word count.
    # If the user is passing many files, it might be > 50K.
    # To keep it simple for v1, we assume any task with more than 10 files to inspect requires confirmation.
    estimated_tokens = len(description.split()) * 1.5 
    if files_to_inspect:
        for fpath in files_to_inspect:
            try:
                estimated_tokens += os.path.getsize(fpath) / 4 # Rough approximation
            except Exception:
                pass
                
    if estimated_tokens > 50000:
        confirm_text = f"Subagent task estimated at >50K tokens ({int(estimated_tokens)}). Confirm dispatch?"
        if not await confirm_with_captain(context, confirm_text):
            return "Error: Subagent dispatch cancelled by Captain (cost control)."
            
    # Setup Sandbox
    sandbox = Sandbox(os.getcwd())
    try:
        sandbox.setup()
        
        task = SubagentTask(
            description=description,
            backend=backend,
            timeout_sec=timeout_sec,
            files_to_inspect=files_to_inspect
        )
        
        task_id = uuid.uuid4().hex[:8]
        
        # Execute
        result = await BACKENDS[backend].dispatch(task, sandbox)
        
        # Log audit
        log_subagent_dispatch(
            task_id=task_id,
            task_description=description,
            backend=backend,
            token_count=result.token_count,
            exit_code=result.exit_code,
            duration_sec=result.duration_sec,
            result_summary=result.summary
        )
        
        # Return response to parent context
        output = f"Subagent `{task_id}` finished with exit code {result.exit_code}.\n"
        output += f"Duration: {result.duration_sec:.1f}s | Tokens: {result.token_count}\n\n"
        output += f"### Summary\n{result.summary}\n\n"
        
        if result.diff:
            output += f"### Proposed File Changes\n```diff\n{result.diff}\n```\n"
            output += "(Note: These changes exist only in the sandbox and were NOT applied to your active workspace yet. Use `write_file` or `terminal` tools if you want to apply them.)"
            
        log_tool_usage("delegate_task", {"description": description, "backend": backend}, f"Dispatched {task_id}", "success")
        return output
        
    finally:
        sandbox.cleanup()
