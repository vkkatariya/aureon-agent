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
                    tool_result = await self.skills.execute_tool(
                        call["function"]["name"], args,
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
