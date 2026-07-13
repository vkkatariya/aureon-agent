"""ReAct loop against Ollama's OpenAI-compat endpoint, with streaming, plan-node soft
check, and auto-clarity override for destructive-action messages."""
import json
import logging
import re

import httpx

from context_builder import build_system_prompt
from plan_node import check_plan

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5

_DESTRUCTIVE_RE = re.compile(
    r"rm\s+-rf|drop\s+table|force[\s-]push|push\s+--force|git\s+reset\s+--hard|truncate\b|mkfs\b",
    re.IGNORECASE,
)

AUTO_CLARITY_NOTE = (
    "SAFETY OVERRIDE: the user's message matches a destructive-action pattern. "
    "Respond in plain, normal prose (not compressed/caveman style) and require "
    "explicit confirmation before describing how to run it."
)


class AgentRuntime:
    def __init__(self, base_url, api_key, model, skill_loader, workspace_dir, memory,
                 fallback_base_url=None, fallback_api_key=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.skills = skill_loader
        self.workspace_dir = workspace_dir
        self.memory = memory
        self.fallback_base_url = fallback_base_url.rstrip("/") if fallback_base_url else None
        self.fallback_api_key = fallback_api_key

    async def run(self, history, session_id, callbacks):
        on_token = callbacks.get("on_token")
        on_tool_use = callbacks.get("on_tool_use")

        last_user = next((m["content"] for m in reversed(history) if m["role"] == "user"), "")

        plan_warning = await check_plan(self.workspace_dir, last_user)
        if plan_warning:
            logger.warning(plan_warning)

        system_prompt = await build_system_prompt(self.workspace_dir, self.skills, self.memory)
        if _DESTRUCTIVE_RE.search(last_user):
            system_prompt += f"\n\n---\n\n{AUTO_CLARITY_NOTE}"

        messages = [{"role": m["role"], "content": m["content"]} for m in history]
        tools = self.skills.get_tools() if self.skills else []
        
        from aureon_agent.tools.terminal import terminal_tool
        from aureon_agent.tools.file import FileTool
        from aureon_agent.tools.web import web_search, web_fetch
        from aureon_agent.tools.todo import TodoTool
        from aureon_agent.tools.clarify import clarify_tool
        
        # Add Tier 1 and Tier 2 tools
        tools.extend([
            {
                "name": "terminal",
                "description": "Executes a terminal command (as list of args). Use for ls, cat, grep, find, git, etc.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "array", "items": {"type": "string"}, "description": "Command and arguments as a list of strings"},
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
            }
        ])

        response_text = ""
        rounds = 0
        while rounds < MAX_TOOL_ROUNDS:
            rounds += 1
            result = await self._call_llm(system_prompt, messages, tools, on_token)

            if result["tool_calls"]:
                messages.append({
                    "role": "assistant",
                    "content": result["text"] or None,
                    "tool_calls": result["tool_calls"],
                })
                for call in result["tool_calls"]:
                    args = json.loads(call["function"]["arguments"] or "{}")
                    if on_tool_use:
                        await on_tool_use(call["function"]["name"], args)
                        
                    tool_name = call["function"]["name"]
                    context_obj = callbacks.get("context", {})
                    
                    if tool_name == "terminal":
                        tool_result = await terminal_tool(context_obj, args.get("command"), args.get("timeout", 30))
                    elif tool_name == "read_file":
                        tool_result = FileTool.read_file(args.get("path"), args.get("max_lines", 500))
                    elif tool_name == "write_file":
                        tool_result = await FileTool.write_file(context_obj, args.get("path"), args.get("content"))
                    elif tool_name == "list_dir":
                        tool_result = FileTool.list_dir(args.get("path"), args.get("pattern", "*"))
                    elif tool_name == "web_search":
                        tool_result = await web_search(args.get("query"), args.get("max_results", 5))
                    elif tool_name == "web_fetch":
                        tool_result = await web_fetch(args.get("url"), args.get("max_chars", 5000))
                    elif tool_name == "todo_read":
                        tool_result = TodoTool.todo_read(args.get("path", "tasks/todo.md"))
                    elif tool_name == "todo_write":
                        tool_result = TodoTool.todo_write(args.get("path", "tasks/todo.md"), args.get("content"), args.get("append", False))
                    elif tool_name == "todo_add":
                        tool_result = TodoTool.todo_add(args.get("path", "tasks/todo.md"), args.get("item"))
                    elif tool_name == "clarify":
                        tool_result = await clarify_tool(context_obj, args.get("question"), args.get("options"), args.get("timeout_sec", 300))
                    else:
                        tool_result = await self.skills.execute_tool(
                            tool_name, args,
                            {"session_id": session_id, "memory": self.memory},
                        )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": json.dumps(tool_result, default=str),
                    })
                continue

            response_text = result["text"]
            break

        return response_text

    async def _call_llm(self, system_prompt, messages, tools, on_token):
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "stream": True,
        }
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
            return await self._stream(self.base_url, self.api_key, body, on_token)
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            if not self.fallback_base_url:
                raise Exception(f"Ollama request failed: {e}") from e
            logger.warning("primary Ollama endpoint failed (%s), falling back to %s", e, self.fallback_base_url)
            return await self._stream(self.fallback_base_url, self.fallback_api_key, body, on_token)

    async def _stream(self, base_url, api_key, body, on_token):
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        text_parts = []
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
