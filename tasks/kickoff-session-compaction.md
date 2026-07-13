# Task: Session compaction for long conversation histories

**Branch:** `feat/aureon-agent-session-compaction` (off `dev`)
**Mode:** Builder
**Complexity:** Medium — LLM-based summarization + history rewrite
**Estimated effort:** 1-2 evenings, ~250-350 LoC + tests

---

## Setup

- **Project:** `aureon-agent`
- **Path on athena:** `~/dev-shared/projects/aureon-agent/`
- **Working directory:** this repo
- **Active branch:** `feat/aureon-agent-session-compaction` (off `dev`)
- **Session name:** `[aureon-agent]-local` (you're the local session, persistent tmux)

## What this is

The agent's `SessionManager` stores every Telegram/Discord turn in SQLite. Long-running sessions grow the context window until the LLM hits token limits, response time increases, and cost scales linearly. This task adds **compaction**: when a session's history exceeds a **model-aware threshold** (computed from the current LLM's context window), summarize the old turns and replace them with a single summary message in the LLM's view. Recent turns stay verbatim. The threshold adapts automatically to the model in use — a 1M-context model compacts much later than a 32K-context model.

Compaction is **invisible to Captain**. The conversation continues; the agent just doesn't re-read the entire history on every turn.

## Reference docs (read before designing)

- **`session_manager.py`** — current session storage (aiosqlite, key=`{channel}:{client_id}`, table `messages`)
- **`agent_runtime.py`** — ReAct loop, where history is loaded for the LLM
- **`memory.py`** — existing key-value + `note:*` namespace, the compaction summary could be a `note:*` entry
- **`context_builder.py`** — assembles system prompt; the compaction summary goes into the user-side history, not the system prompt
- **SQLite FTS5** — already available, could be used for summary indexing (optional v2)

## Decisions confirmed with user (2026-07-13)

- **Threshold (model-aware, not absolute):** compact when `token_count(history) > compact_threshold`, where:
  - `compact_threshold = model.context_window − reserved_response_tokens − system_prompt_tokens`
  - `model.context_window` from a lookup table (`aureon_agent/models.py`): `minimax-m2.5:cloud` → 32K, `minimax-m3:cloud` → 200K, `claude-sonnet-4` → 200K, `claude-sonnet-4[1m]` → 1M, `gpt-4o` → 128K
  - `reserved_response_tokens` = `AUREON_RESERVED_RESPONSE_TOKENS` env (default 4096)
  - `system_prompt_tokens` = measured at runtime on each call (grows as skills/memories accumulate)
  - **Unknown model fallback:** 32K, log WARN with model name
  - **Safety margin:** if `system_prompt_tokens > 50% of context_window`, log ERROR and skip compaction (no room for history anyway)
- **Recent verbatim size (also relative):** `min(4000, compact_threshold * 0.2)`. For 1M context → 8K verbatim. For 32K → 4K. Adapts to available room.
- **Strategy:** sliding window + LLM summary. The summary is a single message that replaces the older messages in the LLM's view (NOT in the database — we keep the full history for audit).
- **What stays in DB:** full history, always. Compaction is a *view* layer, not a *storage* layer. Audit log + replay must work.
- **What changes in DB:** a new `compaction_runs` table tracks: session_id, when, tokens_before, tokens_after, summary_text. The `messages` table is unchanged.
- **What gets summarized:** the old messages are summarized by calling the LLM (cheap model: haiku or `minimax-m2.5:cloud` for local). The summary prompt is: "Summarize this conversation in 200 words or less. Preserve: any facts learned, decisions made, file paths discussed, errors encountered, todos stated. Drop: greetings, hedging, redundant context."
- **What doesn't get summarized:** system prompt, tool definitions, recent verbatim window (per relative sizing above).
- **Trigger:** run compaction at the start of each `AgentRuntime.handle_message()` call, BEFORE the ReAct loop, if `token_count(history) > compact_threshold`. The threshold is computed per-call from current model + current system prompt size.
- **Cost:** ~1K input tokens + 200 output tokens per compaction. At 50 turns/day, that's ~50K tokens/day. Negligible vs the savings.
- **Audit:** every compaction writes to `data/compaction_log.db` (SQLite, append-only): session_id, created_at, tokens_before, tokens_after, summary_text, model_used, context_window_used.
- **Failure mode:** if compaction fails (LLM error, timeout), proceed with the full history (no compaction). Never strand Captain. Log a WARN.
- **Off by default in v1:** add `AUREON_COMPACTION_ENABLED=1` env to enable. Off by default so Captain can test the rest of the system first.

## Read these on session start (in order)

1. `CLAUDE.md` — project context
2. `CONTEXT.md` — stack, infra, decisions
3. `tasks/DEVLOG.md` (last 2 entries) — current world state
4. `tasks/todo.md` — current phase status
5. This file (the kickoff)
6. `session_manager.py` — the storage layer
7. `agent_runtime.py` — where compaction is called
8. `context_builder.py` — how the LLM context is assembled
9. `memory.py` — for the `note:*` namespace pattern

## Your role

You are adding a view-layer optimization to the session history. The data is sacred (don't change `messages` table). The LLM context is a derived view that can be compacted freely. Self-improvement loop: log every compaction to `workspace/tasks/lessons.md` with the before/after token counts and a quality assessment (did the conversation continue coherently?).

---

## 4 sub-tasks (in order)

### Sub-task 1: Token counting + model-aware threshold (60 min)

Add a cheap token counter, a model registry, and a threshold calculator:

- [ ] Add `compaction/__init__.py`, `compaction/counter.py`, `compaction/threshold.py`, `compaction/summarizer.py`, `compaction/log.py`
- [ ] New: `aureon_agent/models.py` — `MODEL_CONTEXT_WINDOWS: dict[str, int]` lookup table:
  ```python
  MODEL_CONTEXT_WINDOWS = {
      "minimax-m2.5:cloud":   32_768,
      "minimax-m3:cloud":    200_000,
      "claude-sonnet-4":      200_000,
      "claude-sonnet-4[1m]":  1_000_000,
      "claude-opus-4":        200_000,
      "gpt-4o":               128_000,
      "gpt-4o-mini":          128_000,
  }
  def get_context_window(model: str) -> int:
      """Returns the context window for a model, or 32K default for unknown."""
  ```
  Unknown model → 32K + WARN log with model name.
- [ ] `compaction/counter.py`:
  - `def count_tokens_messages(messages: list[dict]) -> int` — total token count across messages
  - `def count_tokens_text(text: str) -> int` — single text token count (for system prompt measurement)
  - Cheap heuristic: `len(text) / 4`
  - Use `tiktoken` (already a dep of `httpx`/`openai`) for accuracy when available
- [ ] `compaction/threshold.py`:
  - `def compute_compact_threshold(model: str, system_prompt: str) -> int` — returns `context_window − reserved_response_tokens − system_prompt_tokens`
  - Reads `AUREON_RESERVED_RESPONSE_TOKENS` env (default 4096)
  - Safety check: if `system_prompt_tokens > 0.5 * context_window`, log ERROR and return `0` (skip compaction, no room)
  - Also exports `compute_recent_verbatim_size(compact_threshold: int) -> int = min(4000, int(compact_threshold * 0.2))`
- [ ] `compaction/counter.py`:
  - `def needs_compaction(history_tokens: int, threshold: int) -> bool` — True if `history_tokens > threshold`
  - Caller computes the threshold via `compute_compact_threshold` and passes it in
- [ ] Tests in `tests/test_compaction_counter.py` and `tests/test_compaction_threshold.py`:
  - `count_tokens_messages` matches tiktoken within 20% on a sample corpus
  - `get_context_window("minimax-m2.5:cloud")` → 32768
  - `get_context_window("claude-sonnet-4[1m]")` → 1_000_000
  - `get_context_window("unknown-model")` → 32768 + WARN logged
  - `compute_compact_threshold("minimax-m2.5:cloud", 2K system prompt)` → ~26K
  - `compute_compact_threshold("claude-sonnet-4[1m]", 5K system prompt)` → ~991K
  - `compute_recent_verbatim_size(1_000_000)` → 8000
  - `compute_recent_verbatim_size(20_000)` → 4000
  - `compute_compact_threshold` with system_prompt > 50% context → returns 0 + ERROR logged
  - `needs_compaction(10K, 26K)` → False (1M context model, plenty of room)
  - `needs_compaction(30K, 26K)` → True (32K context model, near full)

### Sub-task 2: Summarization + audit log (90 min)

The LLM call that produces the summary, plus the SQLite log:

- [ ] `compaction/summarizer.py`:
  - `class Summarizer: __init__(self, ollama_client, model: str = "minimax-m2.5:cloud")`
  - `async def summarize(self, messages: list[dict]) -> str` — calls the LLM with the summary prompt, returns the text
  - The prompt: "You are summarizing a conversation between a user and an AI agent. Produce a 200-word summary that preserves: facts learned, decisions made, file paths discussed, errors encountered, todos stated. Drop: greetings, hedging, redundant context. The next agent reading this summary needs to continue the conversation seamlessly. Write in third person ('The user asked...', 'The agent responded...')."
  - Token budget: max 300 output tokens (enforced via API param)
  - Timeout: 30 seconds. On timeout, return the first 500 chars of the messages joined (degraded but never strands)
- [ ] `compaction/log.py`:
  - `class CompactionLog: __init__(self, db_path: str = "data/compaction_log.db")`
  - On `__init__`: ensure schema exists (CREATE TABLE IF NOT EXISTS)
  - `async def record(self, run: CompactionRun) -> None` — INSERT into `compaction_runs` table
  - `async def list_recent(self, session_id: str = None, limit: int = 10) -> list[CompactionRun]`
  - Schema (note: `context_window_used` added for audit):
    ```sql
    CREATE TABLE IF NOT EXISTS compaction_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      created_at TEXT NOT NULL,
      tokens_before INTEGER NOT NULL,
      tokens_after INTEGER NOT NULL,
      summary_text TEXT NOT NULL,
      model_used TEXT NOT NULL,
      context_window_used INTEGER NOT NULL,  -- which model's window was active
      status TEXT NOT NULL  -- 'ok' | 'failed'
    );
    CREATE INDEX IF NOT EXISTS idx_compaction_session ON compaction_runs(session_id, created_at DESC);
    ```
- [ ] Tests in `tests/test_compaction_summarizer.py`:
  - Mock LLM, verify the summary prompt is correct
  - Verify the API call uses max_tokens=300
  - Verify timeout returns a degraded summary (joined text)
  - Verify the audit log writes a row with `context_window_used` populated

### Sub-task 3: View-layer integration in `agent_runtime.py` (60 min)

Wire compaction into the message handling:

- [ ] Add to `agent_runtime.py`:
  - On `handle_message()` entry, BEFORE the ReAct loop:
    1. Load full history via `session_manager.get_history(session_id)`
    2. Measure `system_prompt_tokens = count_tokens_text(current_system_prompt)`
    3. Compute `threshold = compute_compact_threshold(model, current_system_prompt)`
    4. If `threshold == 0` (system prompt too big) → log ERROR, skip compaction, use full history
    5. Else compute `recent_size = compute_recent_verbatim_size(threshold)`
    6. If `not needs_compaction(history_tokens, threshold)` → use full history, proceed
    7. Else compact:
       - Split: keep last `recent_size` tokens verbatim (`recent`), summarize the rest (`old`)
       - Call `summarizer.summarize(old)`
       - Build the LLM context: `[{"role": "system", "content": "<summary>"}, *recent]`
       - The summary message is marked with a special tag so it's identifiable in audit logs
    8. Proceed with the LLM call as normal
- [ ] Config: `AUREON_COMPACTION_ENABLED` env var, default False
- [ ] Cost control: cap the summary input to 16K tokens (don't try to summarize 100K tokens of history in one call)
- [ ] Tests in `tests/test_compaction_integration.py`:
  - Short history + any model → no compaction, full history sent to LLM
  - Long history + small-context model (32K) + env enabled → compaction runs, summary + recent turns sent
  - Long history + large-context model (1M) + env enabled → no compaction (threshold is high, plenty of room)
  - Long history + env disabled → full history sent (no compaction regardless of model)
  - System prompt > 50% of context → ERROR logged, no compaction
  - Summarizer fails (timeout) → falls back to full history, WARN logged

### Sub-task 4: Telemetry + doctor (30 min)

- [ ] Add `aureon-agent compaction-log --last 10` subcommand to `aureon_agent/cli.py`
- [ ] Add `aureon-agent compaction-log --session <id>` filter
- [ ] Add `aureon-agent compaction-log --model <model>` filter (useful to see which model triggered which compaction)
- [ ] Add `aureon-agent doctor` check: `compaction_log.db` is readable, last compaction < 7 days old (only if compaction has ever run)
- [ ] Add `aureon-agent doctor` check: every model in `MODEL_CONTEXT_WINDOWS` lookup is reachable (warn if `AUREON_AGENT_MODEL` points to an unknown model)
- [ ] Update `CLAUDE.md` Commands section with the new subcommand
- [ ] Add a counter to the runtime: `compactions_run_total` — incremented on each successful compaction
- [ ] Add a counter: `compactions_skipped_total` — incremented when compaction is skipped (system prompt too big, env disabled, etc.)

## Acceptance criteria

- [ ] Token counter works with both tiktoken (accurate) and the heuristic (fast fallback)
- [ ] `aureon_agent/models.py` registers all known models with correct context windows
- [ ] Unknown model falls back to 32K + WARN log
- [ ] `compute_compact_threshold(model, system_prompt)` returns `context_window − reserved_response − system_prompt_tokens`
- [ ] `compute_recent_verbatim_size(threshold)` returns `min(4000, threshold * 0.2)`
- [ ] System prompt > 50% of context → ERROR log + skip compaction
- [ ] Summarizer calls the LLM with the right prompt, max_tokens, and timeout
- [ ] Audit log captures every compaction with `context_window_used` populated
- [ ] When `AUREON_COMPACTION_ENABLED=1`, long sessions compact using model-aware threshold
- [ ] When disabled, sessions work as before (no regression)
- [ ] The `messages` SQLite table is never modified (compaction is view-only)
- [ ] `aureon-agent compaction-log --last 10 --model <m>` filters by model
- [ ] `aureon-agent doctor` checks `compaction_log.db` + warns on unknown model
- [ ] Live test: send 30+ messages in a Telegram session on a 32K model, verify compaction runs; on a 1M model, verify it does NOT
- [ ] All existing tests still pass (no regressions)
- [ ] PR opened to `dev`, DEVLOG entry written, todo.md updated

## Out of scope (v1)

- FTS5 search over the summary (v2 — use the summary as a search index)
- Per-session compaction policy (some sessions opt out) — global env var for v1
- Compaction triggered by token budget pressure (LLM rejects a request) — too late, fail open for v1
- Hierarchical compaction (summarize summaries) — only needed at 100K+ token sessions
- Compaction of tool results (they get summarized with the rest)
- Cross-session compaction (merge multiple sessions into one summary) — separate task
- Per-model compaction strategy tuning (different models may want different summary prompts) — single prompt for v1
- Auto-discovery of context window from the LLM API (e.g. `/v1/models` endpoint) — manual lookup table for v1

## Full spec references

- This file: `tasks/kickoff-session-compaction.md`
- Storage: `session_manager.py`
- Runtime: `agent_runtime.py`
- Context assembly: `context_builder.py`
- Existing key-value pattern: `memory.py`
