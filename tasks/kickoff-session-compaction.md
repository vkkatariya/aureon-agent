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

The agent's `SessionManager` stores every Telegram/Discord turn in SQLite. Long-running sessions (50+ turns) grow the context window until the LLM hits token limits, response time increases, and cost scales linearly. This task adds **compaction**: when a session's history exceeds a threshold, summarize the old turns and replace them with a single summary message. Recent turns stay verbatim.

Compaction is **invisible to Captain**. The conversation continues; the agent just doesn't re-read the entire history on every turn.

## Reference docs (read before designing)

- **`session_manager.py`** — current session storage (aiosqlite, key=`{channel}:{client_id}`, table `messages`)
- **`agent_runtime.py`** — ReAct loop, where history is loaded for the LLM
- **`memory.py`** — existing key-value + `note:*` namespace, the compaction summary could be a `note:*` entry
- **`context_builder.py`** — assembles system prompt; the compaction summary goes into the user-side history, not the system prompt
- **SQLite FTS5** — already available, could be used for summary indexing (optional v2)

## Decisions confirmed with user (2026-07-13)

- **Threshold:** compact when history > 8K tokens. Keep the most recent 4K tokens verbatim; summarize everything older.
- **Strategy:** sliding window + LLM summary. The summary is a single message that replaces the older messages in the LLM's view (NOT in the database — we keep the full history for audit).
- **What stays in DB:** full history, always. Compaction is a *view* layer, not a *storage* layer. Audit log + replay must work.
- **What changes in DB:** a new `compaction_runs` table tracks: session_id, when, tokens_before, tokens_after, summary_text. The `messages` table is unchanged.
- **What gets summarized:** the old messages are summarized by calling the LLM (cheap model: haiku or `minimax-m2.5:cloud` for local). The summary prompt is: "Summarize this conversation in 200 words or less. Preserve: any facts learned, decisions made, file paths discussed, errors encountered, todos stated. Drop: greetings, hedging, redundant context."
- **What doesn't get summarized:** system prompt, tool definitions, recent 4K tokens (last 5-10 turns).
- **Trigger:** run compaction at the start of each `AgentRuntime.handle_message()` call, BEFORE the ReAct loop, if `token_count(history) > 8K`.
- **Cost:** ~1K input tokens + 200 output tokens per compaction. At 50 turns/day, that's ~50K tokens/day. Negligible vs the savings.
- **Audit:** every compaction writes to `data/compaction_log.db` (SQLite, append-only): session_id, created_at, tokens_before, tokens_after, summary_text, model_used.
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

### Sub-task 1: Token counting + threshold check (45 min)

Add a cheap token counter and a threshold check:

- [ ] Add `compaction/__init__.py`, `compaction/counter.py`, `compaction/summarizer.py`, `compaction/log.py`
- [ ] `compaction/counter.py`:
  - `def count_tokens(messages: list[dict]) -> int` — uses `tiktoken` if available, else falls back to `len(text) / 4` heuristic
  - Cheap heuristic: each message = `len(content) / 4` tokens. Fast, no dep.
  - Use `tiktoken` (already a dep of `httpx`/`openai`) for accuracy when available
- [ ] `compaction/counter.py`:
  - `def needs_compaction(messages: list[dict], threshold: int = 8000) -> bool`
  - True if total tokens > threshold
- [ ] Tests in `tests/test_compaction_counter.py`:
  - Short history (1K tokens) → `needs_compaction = False`
  - Long history (10K tokens) → `needs_compaction = True`
  - Heuristic matches tiktoken within 20% on a sample corpus

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
  - Schema:
    ```sql
    CREATE TABLE IF NOT EXISTS compaction_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      created_at TEXT NOT NULL,
      tokens_before INTEGER NOT NULL,
      tokens_after INTEGER NOT NULL,
      summary_text TEXT NOT NULL,
      model_used TEXT NOT NULL,
      status TEXT NOT NULL  -- 'ok' | 'failed'
    );
    CREATE INDEX IF NOT EXISTS idx_compaction_session ON compaction_runs(session_id, created_at DESC);
    ```
- [ ] Tests in `tests/test_compaction_summarizer.py`:
  - Mock LLM, verify the summary prompt is correct
  - Verify the API call uses max_tokens=300
  - Verify timeout returns a degraded summary (joined text)
  - Verify the audit log writes a row

### Sub-task 3: View-layer integration in `agent_runtime.py` (60 min)

Wire compaction into the message handling:

- [ ] Add to `agent_runtime.py`:
  - On `handle_message()` entry, BEFORE the ReAct loop:
    1. Load full history via `session_manager.get_history(session_id)`
    2. Call `needs_compaction(history)` — if False, proceed normally
    3. If True:
       - Split: `recent` = last 4K tokens, `old` = everything else
       - Call `summarizer.summarize(old)`
       - Build the LLM context: `[{"role": "system", "content": "<summary>"}, *recent]`
       - The summary message is marked with a special tag so it's identifiable in audit logs
    4. Proceed with the LLM call as normal
- [ ] Config: `AUREON_COMPACTION_ENABLED` env var, default False
- [ ] Cost control: cap the summary input to 16K tokens (don't try to summarize 100K tokens of history in one call)
- [ ] Tests in `tests/test_compaction_integration.py`:
  - Short history → no compaction, full history sent to LLM
  - Long history + env enabled → compaction runs, summary + recent turns sent
  - Long history + env disabled → full history sent (no compaction)
  - Summarizer fails (timeout) → falls back to full history, WARN logged

### Sub-task 4: Telemetry + doctor (30 min)

- [ ] Add `aureon-agent compaction-log --last 10` subcommand to `aureon_agent/cli.py`
- [ ] Add `aureon-agent compaction-log --session <id>` filter
- [ ] Add `aureon-agent doctor` check: `compaction_log.db` is readable, last compaction < 7 days old (only if compaction has ever run)
- [ ] Update `CLAUDE.md` Commands section with the new subcommand
- [ ] Add a counter to the runtime: `compactions_run_total` — incremented on each successful compaction

## Acceptance criteria

- [ ] Token counter works with both tiktoken (accurate) and the heuristic (fast fallback)
- [ ] `needs_compaction()` returns True for > 8K token histories, False otherwise
- [ ] Summarizer calls the LLM with the right prompt, max_tokens, and timeout
- [ ] Audit log captures every compaction (success + failure)
- [ ] When `AUREON_COMPACTION_ENABLED=1`, long sessions compact before the LLM call
- [ ] When disabled, sessions work as before (no regression)
- [ ] The `messages` SQLite table is never modified (compaction is view-only)
- [ ] `aureon-agent compaction-log --last 10` shows recent runs
- [ ] `aureon-agent doctor` checks `compaction_log.db`
- [ ] Live test: send 30+ messages in a Telegram session, verify compaction runs, conversation continues coherently
- [ ] All existing tests still pass (no regressions)
- [ ] PR opened to `dev`, DEVLOG entry written, todo.md updated

## Out of scope (v1)

- FTS5 search over the summary (v2 — use the summary as a search index)
- Per-session compaction policy (some sessions opt out) — global env var for v1
- Compaction triggered by token budget pressure (LLM rejects a request) — too late, fail open for v1
- Hierarchical compaction (summarize summaries) — only needed at 100K+ token sessions
- Compaction of tool results (they get summarized with the rest)
- Cross-session compaction (merge multiple sessions into one summary) — separate task

## Full spec references

- This file: `tasks/kickoff-session-compaction.md`
- Storage: `session_manager.py`
- Runtime: `agent_runtime.py`
- Context assembly: `context_builder.py`
- Existing key-value pattern: `memory.py`
