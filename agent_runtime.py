"""ReAct loop against Ollama's OpenAI-compat endpoint, with streaming, plan-node soft
check, and auto-clarity override for destructive-action messages.

Tool dispatch is unified through ToolRegistry — local skills, inline tools (terminal,
file, web, cron, etc.), and MCP server tools all route through the same path.
"""
import json
import logging
import os
import re

import httpx

from context_builder import build_system_prompt, ContextConfig
from plan_node import require_plan

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5


def _parse_tool_args(raw: "str | None") -> dict:
    """Parse a tool-call arguments string into a dict.

    Models (esp. gemma) sometimes append prose after the JSON, or wrap the
    JSON in code fences. A naive json.loads() then raises
    'Extra data: line 1 column N'. We strip fences and extract the FIRST
    balanced JSON object/array so a trailing sentence doesn't nuke the call.
    """
    if not raw:
        return {}
    s = raw.strip()
    # strip ```json ... ``` fences
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
        s = s.strip()
    # find first balanced { } or [ ]
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start = s.find(open_ch)
        if start == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            c = s[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == open_ch:
                    depth += 1
                elif c == close_ch:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(s[start:i + 1])
                        except json.JSONDecodeError:
                            break
    # fall back to the whole string
    s = s.strip()
    if not s or s[0] not in "{[":
        return {}
    return json.loads(s)


_DESTRUCTIVE_RE = re.compile(
    r"rm\s+-rf|drop\s+table|force[\s-]push|push\s+--force|git\s+reset\s+--hard|truncate\b|mkfs\b",
    re.IGNORECASE,
)

AUTO_CLARITY_NOTE = (
    "SAFETY OVERRIDE: the user's message matches a destructive-action pattern. "
    "Respond in plain, normal prose (not compressed/caveman style) and require "
    "explicit confirmation before describing how to run it."
)

# ── Inline tool schemas ────────────────────────────────────────────
# These are registered via ToolRegistry.register_inline() in _setup_inline_tools().
# Kept here rather than in separate files because they're tightly coupled to
# the agent runtime (cron tools access the DB directly, tool dispatch needs context).

INLINE_TOOL_SCHEMAS = [
    {
        "name": "terminal",
        "description": "Executes a terminal command. Command can be a list of args (preferred) or a single string. Use for ls, cat, grep, find, git, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"oneOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}], "description": "Command as list of args ['ls', '-la', '~/foo'] or as a single string 'ls -la ~/foo'"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"}
            },
            "required": ["command"]
        }
    },
    {
        "name": "read_file",
        "description": "Reads a file from the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to file"},
                "max_lines": {"type": "integer", "description": "Max lines to read (default 500)"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Writes content to a file in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to file"},
                "content": {"type": "string", "description": "Content to write"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "list_dir",
        "description": "Lists contents of a directory in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to directory"},
                "pattern": {"type": "string", "description": "Glob pattern (default *)"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "web_search",
        "description": "Searches the web and returns results.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results (default 5)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "web_fetch",
        "description": "Fetches text content from a URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "max_chars": {"type": "integer", "description": "Max chars to return (default 5000)"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "todo_read",
        "description": "Read the current plan/todo list.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to todo file (default tasks/todo.md)"}
            }
        }
    },
    {
        "name": "todo_write",
        "description": "Overwrite or append to the current plan/todo list.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to todo file (default tasks/todo.md)"},
                "content": {"type": "string", "description": "Content to write"},
                "append": {"type": "boolean", "description": "True to append, False to overwrite"}
            },
            "required": ["content"]
        }
    },
    {
        "name": "todo_add",
        "description": "Add a new item to the plan/todo list (appends as a checklist item).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to todo file (default tasks/todo.md)"},
                "item": {"type": "string", "description": "The item to add"}
            },
            "required": ["item"]
        }
    },
    {
        "name": "clarify",
        "description": "Ask the Captain a clarifying question before proceeding. Blocks execution until answered.",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask"},
                "options": {"type": "array", "items": {"type": "string"}, "description": "Optional multiple choice options"},
                "timeout_sec": {"type": "integer", "description": "Timeout in seconds (default 300)"}
            },
            "required": ["question"]
        }
    },
    {
        "name": "delegate_task",
        "description": "Dispatch a subagent (using claude-code) to perform parallel work, research, or code review in a sandbox. Returns the result and any proposed file changes. Takes a few minutes.",
        "parameters": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "The task for the subagent"},
                "backend": {"type": "string", "description": "Backend to use (default claude-code)"},
                "timeout_sec": {"type": "integer", "description": "Timeout in seconds (default 300)"},
                "files_to_inspect": {"type": "array", "items": {"type": "string"}, "description": "Optional list of files to inspect"}
            },
            "required": ["description"]
        }
    },
    {
        "name": "cron_create",
        "description": "Create a scheduled cron job. The bot will run the prompt at the scheduled time and deliver the output to Telegram. Schedule can be: cron expression ('0 8 * * *' = daily 8am, '0 */6 * * *' = every 6h), interval ('30m', '2h', '1d'), or one-shot ISO timestamp ('2026-07-15T09:00:00'). Use --repeat 1 for one-shot reminders (auto-deletes after 1 run).",
        "parameters": {
            "type": "object",
            "properties": {
                "schedule": {"type": "string", "description": "Cron expr '0 8 * * *', interval '30m'/'2h'/'1d', or ISO '2026-07-15T09:00:00'"},
                "name": {"type": "string", "description": "Human-readable job name"},
                "prompt": {"type": "string", "description": "Self-contained task instruction (agent has no context, must be fully self-contained)"},
                "skills": {"type": "array", "items": {"type": "string"}, "description": "Skills to load (e.g. ['homelab-health']). Empty = bare agent."},
                "deliver": {"type": "string", "description": "Delivery channel: telegram (default), discord, local, all"},
                "repeat": {"type": "integer", "description": "0 = infinite (default), 1 = one-shot (auto-delete after 1 run), N = N runs then delete"}
            },
            "required": ["schedule", "name", "prompt"]
        }
    },
    {
        "name": "cron_list",
        "description": "List all scheduled cron jobs with their schedule, next run, and status.",
        "parameters": {"type": "object", "properties": {}}
    },
    {
        "name": "cron_remove",
        "description": "Remove (delete) a scheduled cron job by its ID. Use cron_list first to find the ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The 8-character job ID"}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "cron_pause",
        "description": "Pause a scheduled cron job (keeps it, but it won't run until resumed).",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The 8-character job ID"}
            },
            "required": ["job_id"]
        }
    },
    {
        "name": "cron_resume",
        "description": "Resume a paused cron job.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "The 8-character job ID"}
            },
            "required": ["job_id"]
        }
    },
]


class AgentRuntime:
    def __init__(self, base_url, api_key, model, skill_loader, workspace_dir, memory,
                 fallback_base_url=None, fallback_api_key=None,
                 tool_registry=None, thinking=False, thinking_budget=1024):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.skills = skill_loader
        self.workspace_dir = workspace_dir
        self.memory = memory
        self.fallback_base_url = fallback_base_url.rstrip("/") if fallback_base_url else None
        self.fallback_api_key = fallback_api_key
        self.registry = tool_registry
        self.thinking = thinking
        self.thinking_budget = thinking_budget

    def setup_registry(self, registry):
        """Set the tool registry and register all inline tools.

        Called after __init__ when the registry is constructed in cli.py.
        """
        self.registry = registry
        self._register_inline_tools()

    def _register_inline_tools(self):
        """Register all inline tool schemas and their dispatch handlers."""
        from aureon_agent.tools.terminal import terminal_tool
        from aureon_agent.tools.file import FileTool
        from aureon_agent.tools.web import web_search, web_fetch
        from aureon_agent.tools.todo import TodoTool
        from aureon_agent.tools.clarify import clarify_tool
        from aureon_agent.subagent import delegate_task_tool

        # Map tool names to their handlers.
        # Each handler must be: async (args: dict, context: dict) → str
        # Sync tools are wrapped with _wrap_sync().

        async def _h_terminal(args, ctx):
            return await terminal_tool(ctx, args.get("command"), args.get("timeout", 30))

        async def _h_read_file(args, ctx):
            result = FileTool.read_file(args.get("path"), args.get("max_lines", 500))
            return json.dumps(result, default=str) if isinstance(result, dict) else str(result)

        async def _h_write_file(args, ctx):
            return await FileTool.write_file(ctx, args.get("path"), args.get("content"))

        async def _h_list_dir(args, ctx):
            result = FileTool.list_dir(args.get("path"), args.get("pattern", "*"))
            return json.dumps(result, default=str) if isinstance(result, dict) else str(result)

        async def _h_web_search(args, ctx):
            return await web_search(args.get("query"), args.get("max_results", 5))

        async def _h_web_fetch(args, ctx):
            return await web_fetch(args.get("url"), args.get("max_chars", 5000))

        async def _h_todo_read(args, ctx):
            result = TodoTool.todo_read(args.get("path", "tasks/todo.md"))
            return json.dumps(result, default=str) if isinstance(result, dict) else str(result)

        async def _h_todo_write(args, ctx):
            result = TodoTool.todo_write(args.get("path", "tasks/todo.md"), args.get("content"), args.get("append", False))
            return json.dumps(result, default=str) if isinstance(result, dict) else str(result)

        async def _h_todo_add(args, ctx):
            result = TodoTool.todo_add(args.get("path", "tasks/todo.md"), args.get("item"))
            return json.dumps(result, default=str) if isinstance(result, dict) else str(result)

        async def _h_clarify(args, ctx):
            return await clarify_tool(ctx, args.get("question"), args.get("options"), args.get("timeout_sec", 300))

        async def _h_delegate_task(args, ctx):
            return await delegate_task_tool(ctx, args.get("description"), args.get("backend", "claude-code"), args.get("timeout_sec", 300), args.get("files_to_inspect"))

        async def _h_cron_create(args, ctx):
            return await self._cron_create(args)

        async def _h_cron_list(args, ctx):
            return await self._cron_list()

        async def _h_cron_remove(args, ctx):
            return await self._cron_remove(args.get("job_id", ""))

        async def _h_cron_pause(args, ctx):
            return await self._cron_pause(args.get("job_id", ""))

        async def _h_cron_resume(args, ctx):
            return await self._cron_resume(args.get("job_id", ""))

        handlers = {
            "terminal": _h_terminal,
            "read_file": _h_read_file,
            "write_file": _h_write_file,
            "list_dir": _h_list_dir,
            "web_search": _h_web_search,
            "web_fetch": _h_web_fetch,
            "todo_read": _h_todo_read,
            "todo_write": _h_todo_write,
            "todo_add": _h_todo_add,
            "clarify": _h_clarify,
            "delegate_task": _h_delegate_task,
            "cron_create": _h_cron_create,
            "cron_list": _h_cron_list,
            "cron_remove": _h_cron_remove,
            "cron_pause": _h_cron_pause,
            "cron_resume": _h_cron_resume,
        }

        for schema in INLINE_TOOL_SCHEMAS:
            name = schema["name"]
            handler = handlers.get(name)
            if handler:
                self.registry.register_inline(name, schema, handler)

    async def run(self, history, session_id, callbacks):
        on_token = callbacks.get("on_token")
        on_tool_use = callbacks.get("on_tool_use")
        on_thinking = callbacks.get("on_thinking")

        last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")

        ok, reason = require_plan(self.workspace_dir, last_user)
        if not ok:
            return reason

        system_prompt = await build_system_prompt(
            self.workspace_dir, self.skills, self.memory,
            ctx_config=ContextConfig.from_env(),
        )
        if _DESTRUCTIVE_RE.search(last_user):
            system_prompt += f"\n\n---\n\n{AUTO_CLARITY_NOTE}"

        messages = [{"role": m["role"], "content": m["content"]} for m in history]

        # Get tools from registry (merged: skills + inline + MCP)
        if self.registry:
            tools = self.registry.get_all()
        else:
            # Fallback: skills-only (backward compat for tests without registry)
            tools = self.skills.get_tools() if self.skills else []

        response_text = ""
        rounds = 0
        while rounds < MAX_TOOL_ROUNDS:
            rounds += 1
            result = await self._call_llm(system_prompt, messages, tools, on_token, on_thinking=on_thinking)

            if not result.get("text") and not result.get("tool_calls"):
                logger.warning("agent.run: LLM returned EMPTY response on round %d — last_user=%r", rounds, messages[-1].get("content", "")[:100] if messages else "")

            if result["tool_calls"]:
                messages.append({
                    "role": "assistant",
                    "content": result["text"] or None,
                    "tool_calls": result["tool_calls"],
                })
                for call in result["tool_calls"]:
                    args = _parse_tool_args(call["function"]["arguments"])
                    if on_tool_use:
                        await on_tool_use(call["function"]["name"], args)

                    tool_name = call["function"]["name"]
                    context_obj = callbacks.get("context", {})
                    context_obj["session_id"] = session_id
                    context_obj["memory"] = self.memory

                    # Dispatch through registry
                    if self.registry:
                        tool_result = await self.registry.dispatch(
                            tool_name, args, context_obj)
                    else:
                        # Fallback: skill-only dispatch
                        tool_result = await self.skills.execute_tool(
                            tool_name, args,
                            {"session_id": session_id, "memory": self.memory},
                        )

                    # Normalize to string
                    if isinstance(tool_result, dict):
                        tool_result = json.dumps(tool_result, default=str)
                    elif not isinstance(tool_result, str):
                        tool_result = str(tool_result)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": tool_result,
                    })
                continue

            response_text = result["text"] or ""
            logger.info("agent.run: round %d ended with text=%r tool_calls=%d", rounds, response_text[:100] if response_text else "", len(result.get("tool_calls") or []))
            break

        # If we hit MAX_TOOL_ROUNDS without a final text response, force one more call
        # without tools so the LLM has to summarize what it learned.
        if not response_text and rounds >= MAX_TOOL_ROUNDS:
            logger.warning("agent.run: hit MAX_TOOL_ROUNDS=%d with no text, forcing final summary call", MAX_TOOL_ROUNDS)
            summary_prompt = system_prompt + "\n\n---\n\nYou have used all your tool calls. Now provide a final text response to the user based on what you learned. Do not call any more tools."
            final_body = {
                "model": self.model,
                "messages": [{"role": "system", "content": summary_prompt}] + messages + [{"role": "user", "content": "[system] Summarize your findings as a final response to the user. Do not call tools."}],
                "stream": True,
            }
            try:
                final_result = await self._stream(self.base_url, self.api_key, final_body, on_token)
                response_text = final_result["text"] or ""
                logger.info("agent.run: forced summary call returned text=%r (length=%d)", response_text[:100] if response_text else "", len(response_text))
            except Exception as e:
                logger.error("agent.run: forced summary call failed: %s", e)

        logger.info("agent.run: returning response_text=%r (length=%d)", response_text[:100] if response_text else "", len(response_text))
        return response_text

    # ── Cron tool handlers (inline — tightly coupled to agent state) ──

    async def _cron_create(self, args: dict) -> str:
        """Create a cron job from LLM tool call."""
        import time
        import uuid
        import aiosqlite
        from aureon_agent.cron_schedule import detect_schedule_type, calc_next_run

        schedule = args.get("schedule", "")
        name = args.get("name", "")
        prompt = args.get("prompt", "")
        skills = args.get("skills", [])
        deliver = args.get("deliver", "telegram")
        repeat = args.get("repeat", 0)

        if not schedule or not name or not prompt:
            return "Error: schedule, name, and prompt are required"

        try:
            schedule_type = detect_schedule_type(schedule)
            next_run = calc_next_run(schedule, schedule_type, time.time())
        except Exception as e:
            return f"Error: invalid schedule: {e}"

        job_id = uuid.uuid4().hex[:8]
        chat_id = os.environ.get("TELEGRAM_ALLOWED_CHATS", "").split(",")[0]

        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cron_jobs.db")
        async with aiosqlite.connect(db_path) as db:
            await db.execute("""
                INSERT INTO cron_jobs (id, name, schedule, schedule_type, prompt, skills, deliver, chat_id, repeat, enabled, created_at, next_run_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """, (job_id, name, schedule, schedule_type, prompt, json.dumps(skills), deliver, chat_id, repeat, time.time(), next_run))
            await db.commit()

        from datetime import datetime
        next_str = datetime.fromtimestamp(next_run).strftime("%Y-%m-%d %H:%M")
        return f"Created cron job {job_id}: '{name}'\nSchedule: {schedule} ({schedule_type})\nNext run: {next_str}\nDeliver: {deliver}\nRepeat: {'one-shot' if repeat == 1 else 'infinite' if repeat == 0 else f'{repeat} times'}"

    async def _cron_list(self) -> str:
        """List all cron jobs."""
        import aiosqlite
        from datetime import datetime

        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cron_jobs.db")
        if not os.path.exists(db_path):
            return "No cron jobs configured."

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM cron_jobs ORDER BY next_run_at")
            jobs = await cursor.fetchall()

        if not jobs:
            return "No cron jobs configured."

        lines = []
        for j in jobs:
            status = "active" if j["enabled"] else "paused"
            next_str = datetime.fromtimestamp(j["next_run_at"]).strftime("%m-%d %H:%M") if j["next_run_at"] else "N/A"
            lines.append(f"  {j['id']} [{status}] {j['name']}\n    schedule: {j['schedule']}  deliver: {j['deliver']}\n    next: {next_str}  runs: {j['run_count']}")
        return "\n".join(lines)

    async def _cron_remove(self, job_id: str) -> str:
        """Remove a cron job."""
        import aiosqlite

        if not job_id:
            return "Error: job_id required"

        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cron_jobs.db")
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("DELETE FROM cron_jobs WHERE id=?", (job_id,))
            await db.commit()
            if cursor.rowcount == 0:
                return f"Error: job {job_id} not found"
        return f"Removed cron job {job_id}"

    async def _cron_pause(self, job_id: str) -> str:
        """Pause a cron job."""
        import aiosqlite

        if not job_id:
            return "Error: job_id required"

        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cron_jobs.db")
        async with aiosqlite.connect(db_path) as db:
            cursor = await db.execute("UPDATE cron_jobs SET enabled=0 WHERE id=?", (job_id,))
            await db.commit()
            if cursor.rowcount == 0:
                return f"Error: job {job_id} not found"
        return f"Paused cron job {job_id}"

    async def _cron_resume(self, job_id: str) -> str:
        """Resume a paused cron job."""
        import time
        import aiosqlite
        from aureon_agent.cron_schedule import calc_next_run

        if not job_id:
            return "Error: job_id required"

        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cron_jobs.db")
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM cron_jobs WHERE id=?", (job_id,))
            job = await cursor.fetchone()
            if not job:
                return f"Error: job {job_id} not found"

            next_run = calc_next_run(job["schedule"], job["schedule_type"], time.time())
            await db.execute("UPDATE cron_jobs SET enabled=1, next_run_at=? WHERE id=?", (next_run, job_id))
            await db.commit()

        from datetime import datetime
        next_str = datetime.fromtimestamp(next_run).strftime("%m-%d %H:%M")
        return f"Resumed cron job {job_id}, next run: {next_str}"

    # ── LLM communication ──────────────────────────────────────────

    def _thinking_field(self):
        m = self.model.lower()
        if m.startswith("deepseek") or m.startswith("qwen"):
            return {"reasoning_effort": "high"}
        return {"thinking": {"type": "enabled", "budget_tokens": self.thinking_budget}}

    async def _call_llm(self, system_prompt, messages, tools, on_token, on_thinking=None):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "stream": True,
        }
        if self.thinking:
            body.update(self._thinking_field())
            
        if tools:
            body["tools"] = [{
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            } for t in tools]

        try:
            return await self._stream(self.base_url, self.api_key, body, on_token, on_thinking=on_thinking)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            if not self.fallback_base_url:
                raise Exception(f"Ollama request failed: {e}") from e
            logger.warning("primary Ollama endpoint failed (%s), falling back to %s", e, self.fallback_base_url)
            return await self._stream(self.fallback_base_url, self.fallback_api_key, body, on_token, on_thinking=on_thinking)

    async def _stream(self, base_url, api_key, body, on_token, on_thinking=None):
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        text_parts = []
        thinking_parts = []
        tool_calls = {}

        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST", f"{base_url}/chat/completions", headers=headers, json=body,
            ) as res:
                if res.status_code != 200:
                    error_body = await res.aread()
                    raise Exception(f"Ollama API error ({res.status_code}): {error_body.decode()}")

                async for line in res.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if payload == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    delta = chunk["choices"][0].get("delta", {})

                    reasoning = delta.get("reasoning_content") or delta.get("reasoning") or delta.get("thinking")
                    if reasoning:
                        thinking_parts.append(reasoning)
                        if on_thinking:
                            await on_thinking(reasoning)

                    if delta.get("content"):
                        text_parts.append(delta["content"])
                        if on_token:
                            await on_token(delta["content"])

                    for tc in delta.get("tool_calls", []) or []:
                        idx = tc["index"]
                        entry = tool_calls.setdefault(idx, {
                            "id": tc.get("id"), "type": "function",
                            "function": {"name": "", "arguments": ""},
                        })
                        if tc.get("id"):
                            entry["id"] = tc["id"]
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            entry["function"]["name"] += fn["name"]
                        if fn.get("arguments"):
                            entry["function"]["arguments"] += fn["arguments"]

        ordered_tool_calls = [tool_calls[i] for i in sorted(tool_calls)]
        return {"text": "".join(text_parts), "tool_calls": ordered_tool_calls or None}
