"""ReAct loop against Ollama's OpenAI-compat endpoint, with streaming, plan-node soft
check, auto-clarity override for destructive-action messages, and model-aware
session compaction (view-layer only — never rewrites session_manager's messages)."""
import json
import logging
import os
import re

import httpx

from aureon_agent.models import get_context_window
from compaction.counter import count_tokens_messages, count_tokens_text, needs_compaction
from compaction.log import CompactionRun
from compaction.summarizer import Summarizer
from compaction.threshold import compute_compact_threshold, compute_recent_verbatim_size
from context_builder import build_system_prompt
from lessons import append_lesson
from plan_node import check_plan

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
COMPACTION_SUMMARY_TAG = "[compacted-history-summary]"
COMPACTION_SUMMARIZE_INPUT_CAP_TOKENS = 16_000

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
                 fallback_base_url=None, fallback_api_key=None, compaction_log=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.skills = skill_loader
        self.workspace_dir = workspace_dir
        self.memory = memory
        self.fallback_base_url = fallback_base_url.rstrip("/") if fallback_base_url else None
        self.fallback_api_key = fallback_api_key
        self.compaction_log = compaction_log
        self._summarizer = None
        self.compactions_run_total = 0
        self.compactions_skipped_total = 0

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
        messages = await self._maybe_compact(messages, session_id, system_prompt)
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

    def _get_summarizer(self):
        if self._summarizer is None:
            model = os.getenv("AUREON_SUMMARY_MODEL", self.model)
            self._summarizer = Summarizer(self.base_url, self.api_key, model)
        return self._summarizer

    @staticmethod
    def _cap_tokens_tail(messages, max_tokens):
        """Keep the tail (most recent) messages within a token budget — the
        oldest-of-the-old matters least when we're already summarizing."""
        capped = []
        total = 0
        for msg in reversed(messages):
            tokens = count_tokens_text(msg.get("content") or "")
            if capped and total + tokens > max_tokens:
                break
            capped.append(msg)
            total += tokens
        capped.reverse()
        return capped

    async def _maybe_compact(self, messages, session_id, system_prompt):
        if os.getenv("AUREON_COMPACTION_ENABLED", "0").lower() not in ("1", "true"):
            return messages

        threshold = compute_compact_threshold(self.model, system_prompt)
        if threshold <= 0:
            self.compactions_skipped_total += 1
            return messages

        history_tokens = count_tokens_messages(messages)
        if not needs_compaction(history_tokens, threshold):
            return messages

        try:
            return await self._compact(messages, session_id, threshold, history_tokens)
        except Exception as e:
            logger.warning("compaction failed for %s (%s), proceeding with full history", session_id, e)
            self.compactions_skipped_total += 1
            return messages

    async def _compact(self, messages, session_id, threshold, history_tokens):
        recent_size = compute_recent_verbatim_size(threshold)
        recent = self._cap_tokens_tail(messages, recent_size)
        old = messages[:len(messages) - len(recent)]

        if not old:
            self.compactions_skipped_total += 1
            return messages

        summarizer = self._get_summarizer()
        old_capped = self._cap_tokens_tail(old, COMPACTION_SUMMARIZE_INPUT_CAP_TOKENS)
        summary_text = await summarizer.summarize(old_capped)

        compacted = [{"role": "system", "content": f"{COMPACTION_SUMMARY_TAG} {summary_text}"}] + recent
        tokens_after = count_tokens_messages(compacted)

        if self.compaction_log:
            await self.compaction_log.record(CompactionRun(
                session_id=session_id,
                tokens_before=history_tokens,
                tokens_after=tokens_after,
                summary_text=summary_text,
                model_used=self.model,
                context_window_used=get_context_window(self.model),
                status="ok",
            ))
        self.compactions_run_total += 1
        logger.info(
            "compacted session %s: %d -> %d tokens (model=%s)",
            session_id, history_tokens, tokens_after, self.model,
        )
        await self._log_compaction_lesson(session_id, history_tokens, tokens_after)
        return compacted

    async def _log_compaction_lesson(self, session_id, tokens_before, tokens_after):
        """Self-improvement loop entry per compaction run (doctrine rule 3). Not a
        mistake-correction — repurposes the lessons.md template to keep a running,
        human-readable record of compaction quality since data/compaction_log.db
        isn't doctrine-visible to Captain."""
        reduction_pct = round((1 - tokens_after / tokens_before) * 100, 1) if tokens_before else 0
        try:
            await append_lesson(
                self.workspace_dir,
                context=f"Session compaction fired for {session_id} (model={self.model}).",
                what_went_wrong="N/A — automatic view-layer compaction, not a correction.",
                root_cause=f"History exceeded the model-aware token threshold for {self.model}.",
                prevention_rule=(
                    f"{tokens_before} -> {tokens_after} tokens ({reduction_pct}% reduction). "
                    "Quality (did the conversation stay coherent after this point?) is not "
                    "auto-verified — spot-check if the user reports confusion or repetition."
                ),
                title=f"Session compaction — {session_id}",
            )
        except Exception as e:
            logger.warning("failed to write compaction lesson for %s: %s", session_id, e)

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
