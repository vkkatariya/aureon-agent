# Kickoff: thinking mode (reasoning tokens) in aureon-agent

**Context:** Captain wants the agent to run with **thinking/reasoning enabled** (model reasons before answering) for better quality. Currently `_call_llm` sends a bare OpenAI-compatible body with no thinking param — thinking is OFF. This kickoff adds a **config-flagged thinking mode**: inject the provider-correct thinking field, capture reasoning tokens during streaming, and surface them in the TUI/Telegram as a separate "thinking" panel (not mixed into the final answer).

**CRITICAL FINDING (probed live 2026-07-19, gemma4:31b-cloud on Ollama `/v1`):**
- Model in prod: `gemma4:31b-cloud`, base `http://127.0.0.1:11434/v1` (Ollama OpenAI-compatible).
- `reasoning: true` → **400** (Ollama rejects: "cannot unmarshal bool into Reasoning").
- `think: true` → 200 but **no reasoning emitted** in stream.
- `thinking: {"type":"enabled","budget_tokens":512}` → **200 (accepted schema)** but stream deltas carry ONLY `content`/`role` — **no `reasoning_content` / `reasoning` field**.
- **Conclusion:** gemma4:31b-cloud on this Ollama build does NOT emit thinking tokens through the OpenAI-compatible endpoint. The plumbing below is correct + future-proof, but it will be a **no-op on the current model** until a thinking-capable model is behind the endpoint (e.g. a `gemma4:thinking`/reason build, DeepSeek-R1, Qwen-Thinking, or Claude via an Anthropic endpoint that streams `reasoning_content`).
- **Verification gate:** the kickoff's tests use a MOCK that emits `reasoning_content` deltas (so the plumbing is proven). A live probe step checks the real endpoint; if absent, thinking is silently inert (answer still works) — no crash.

## Current state (verified)
- `agent_runtime.py:_call_llm` (line 562) builds `body = {model, messages, stream:True}` (+ `tools` if present). No thinking field.
- `_stream` (line 586) parses SSE; captures `delta.content` → `on_token`, `delta.tool_calls` → tool parsing. **No `reasoning_content` capture.**
- `run()` (line 342) calls `_call_llm(system_prompt, messages, tools, on_token)`. `callbacks` dict carries `on_token`/`on_tool_use` (from Telegram `_on_message` / REPL).
- Model + base_url + api_key from env (`OLLAMA_MODEL`, `OLLAMA_BASE_URL`, `OLLAMA_API_KEY`) in `cli.build_runtime`.
- TUI (`repl.py`) streams `on_token` to stdout; Telegram streams to a placeholder edit.

## Design

### 1. Config flag
- New env: `AUREON_THINKING` (default `"false"`), optional `AUREON_THINKING_BUDGET` (tokens, default 1024).
- `cli.build_runtime` reads both, passes to `AgentRuntime(..., thinking=..., thinking_budget=...)`.
- `AgentRuntime.__init__` stores `self.thinking: bool`, `self.thinking_budget: int`.

### 2. `_call_llm` body injection (provider-aware)
Add a helper `_thinking_field()` returning the correct body fragment based on `self.model` prefix:
- `claude*` / `gemma*` (Anthropic-style schema accepted by Ollama): `{"thinking": {"type": "enabled", "budget_tokens": budget}}`
- `deepseek*` / `qwen*` (OpenAI reasoning schema): `{"reasoning_effort": "high"}` or `{"reasoning": True}` (whichever the target accepts — gate by probe)
- fallback: `{"thinking": {"type":"enabled","budget_tokens":budget}}` (most-compatible)
- Only inject when `self.thinking` is True.
- Keep it a small dict-merge so future models are one-line additions.

### 3. Streaming reasoning capture (`_stream`)
- Add `on_thinking` to `_call_llm` signature + thread it into `_stream`.
- In the SSE loop, capture reasoning from the field the model uses:
  - `delta.reasoning_content` (DeepSeek / Ollama-thinking)
  - `delta.reasoning` (some Ollama)
  - `delta.thinking` (Anthropic-native delta)
  - Accumulate into `thinking_parts`; call `await on_thinking(token)` per chunk if provided.
- `tool_calls` + `content` handling unchanged.

### 4. `run()` callback threading
- `run()` accepts `callbacks` with optional `on_thinking`. Pass `callbacks.get("on_thinking")` into `_call_llm(..., on_thinking=...)`.
- Default `on_thinking = None` → no-op (backward compatible; Telegram/TUI opt in).

### 5. UX surfaces
- **TUI (`repl.py`):** add `on_thinking` that prints to a dim `rich` panel titled "thinking…" (or streams inline in a dim style), cleared/replaced when the final answer streams. Keep it light.
- **Telegram (`channels/telegram.py`):** optional — stream thinking to the placeholder with a dim prefix, or skip (thinking can be noisy in chat). Default: **off in Telegram** (only TUI shows thinking), to avoid chat clutter. Make it a per-channel choice; Telegram keeps `on_thinking=None`.
- Banner (from tui-polish kickoff) can show `thinking: on/off` like the MCP-office notice.

## Constraints
- **Backward compatible:** `on_thinking=None` default → identical behavior when `AUREON_THINKING=false`.
- **No thinking on current gemma4:31b-cloud** (proven) — must not crash or hang; answer still streams. The injected `thinking` block is accepted (200) but inert.
- **No new deps.**
- **Secrets never in thinking text** (it's model output, not user/secret).
- **Caveman mode** applies to final answer, not reasoning (reasoning is internal).

## Tests
- `tests/test_thinking.py` (new): mock `_stream` to emit `reasoning_content` deltas → assert `on_thinking` called with those tokens and final `on_token` excludes them.
- `tests/test_agent_loop.py` (extend): `AUREON_THINKING=true` → `_call_llm` body contains the thinking field; `false` → absent.
- Mock SSE harness (reuse existing stream-test pattern) injecting `data: {"choices":[{"delta":{"reasoning_content":"..."}}]}` then content deltas.

## Verification
- `python -m pytest tests/ -q` green; `ruff` clean.
- Unit: thinking field injected when flag on; reasoning captured + separated from answer.
- **Live probe:** `curl`/script the endpoint with `thinking:{type:enabled}` + stream → check for `reasoning_content` delta. On gemma4:31b-cloud: **absent** → documented no-op. On a thinking model: present → TUI shows thinking panel.
- `AUREON_THINKING=false` (default) → zero behavior change, answer identical.

## Suggested commits
- `feat(thinking): config-flagged thinking mode — provider-aware body + reasoning streaming (on_thinking callback)`
- `test(thinking): reasoning capture + body injection tests`
- `feat(tui): show thinking panel when AUREON_THINKING=true`
