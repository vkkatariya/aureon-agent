import asyncio
import json
import logging
import time
from .base import SubagentBackend, SubagentTask, SubagentResult
from .sandbox import Sandbox

logger = logging.getLogger(__name__)

class ClaudeCodeBackend(SubagentBackend):
    async def dispatch(self, task: SubagentTask, sandbox: Sandbox) -> SubagentResult:
        # Create briefing.md
        briefing_path = f"{sandbox.temp_dir}/workspace/briefing.md"
        with open(briefing_path, "w", encoding="utf-8") as f:
            f.write(task.description)
            
        cmd = [
            "claude", 
            "-p", "Read briefing.md and perform the requested task. Then summarize your work.",
            "--output-format", "json"
        ]
        
        start_time = time.time()
        try:
            # We run in sandbox.temp_dir/workspace
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=f"{sandbox.temp_dir}/workspace",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=task.timeout_sec)
                duration = time.time() - start_time
                
                # Parse JSON output
                stdout_str = stdout.decode("utf-8").strip()
                summary = stdout_str
                token_count = 0 # Claude doesn't always provide tokens in JSON stdout easily, fallback
                
                try:
                    if stdout_str:
                        # Find the last line that is valid JSON (ignoring trailing noise)
                        lines = stdout_str.splitlines()
                        for line in reversed(lines):
                            try:
                                data = json.loads(line)
                                if "result" in data:
                                    summary = data["result"]
                                    if "usage" in data:
                                        token_count = data["usage"].get("input_tokens", 0) + data["usage"].get("output_tokens", 0)
                                    break
                            except json.JSONDecodeError:
                                continue
                except Exception:
                    pass # Keep raw stdout as summary
                    
                diff = sandbox.get_diff()
                
                return SubagentResult(
                    exit_code=process.returncode,
                    duration_sec=duration,
                    token_count=token_count,
                    summary=summary,
                    diff=diff
                )
                
            except asyncio.TimeoutError:
                process.kill()
                await process.communicate()
                duration = time.time() - start_time
                return SubagentResult(
                    exit_code=-1,
                    duration_sec=duration,
                    token_count=0,
                    summary=f"Error: Subagent timed out after {task.timeout_sec} seconds.",
                    diff=""
                )
        except Exception as e:
            duration = time.time() - start_time
            return SubagentResult(
                exit_code=-2,
                duration_sec=duration,
                token_count=0,
                summary=f"Error launching subagent: {e}",
                diff=""
            )
