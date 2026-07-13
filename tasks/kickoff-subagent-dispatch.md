# Task: Subagent dispatch via `delegate_task`

**Branch:** `feat/aureon-agent-subagent-dispatch` (off `dev`)
**Mode:** Builder
**Complexity:** Non-trivial — tool integration + sandbox + result routing
**Estimated effort:** 2 evenings, ~400-500 LoC + tests

---

## Setup

- **Project:** `aureon-agent`
- **Path on athena:** `~/dev-shared/projects/aureon-agent/`
- **Working directory:** this repo
- **Active branch:** `feat/aureon-agent-subagent-dispatch` (off `dev`)
- **Session name:** `[aureon-agent]-local` (you're the local session, persistent tmux)

## What this is

Wire a `delegate_task` tool into the agent's tool registry. When the agent receives a request that needs parallel work, long-running research, or a code review, it can spawn a subagent (a separate Claude Code / OpenCode session) and get the result back. This is the single feature that turns aureon-agent from "Telegram chatbot" into "AI operator".

The doctrine for this is already loaded (Olympus orchestration in `~/.openclaw/workspace/MEMORY.md`), but the wiring into the agent runtime is missing. This task adds that wiring.

## Reference docs (read before designing)

- **`~/.openclaw/workspace/MEMORY.md`** §"Olympus" — the 3-node orchestration (athena = infra, hermes = interactive, atlas = production)
- **`~/.openclaw/workspace/MEMORY.md`** §"🦾 Lessons from 2026-06-16/17" — the parallel dispatch patterns + gotchas
- **`~/.openclaw/workspace/MEMORY.md`** §"Coding Agents" — agent roster (claude-code, opencode, codex, abacus, agy, copilot)
- **`~/.openclaw/workspace/MEMORY.md`** §"delegate_task" — invocation patterns, subagent model selection
- **Existing tool integration:** `skill_loader.py` — how tools are registered, called, results returned
- **ReAct loop:** `agent_runtime.py` — where `delegate_task` gets plugged in

## Decisions confirmed with user (2026-07-13)

- **Subagent backend:** delegate to `claude-code` CLI (already on athena via `~/dev-shared/projects/portfolio-website/.venv` style invocation) for v1. OpenCode is the second option if claude-code is unavailable. No new subagent runtime is built — we shell out.
- **Result format:** subagent returns a markdown file (or stdout) that gets pasted into the parent agent's context. Don't try to merge into the conversation mid-stream — wait for the full subagent output, then resume.
- **Scope:** v1 supports ONE concurrent subagent (simple FIFO queue). Multiple concurrent = v2.
- **Timeout:** 5 minute hard timeout per subagent. If exceeded, kill the subprocess, return a "subagent timed out" message to Captain, log the failure.
- **Sandbox:** subagent runs in a temp directory (`/tmp/aureon-subagent-<uuid>/`) with the source repo read-only bind-mounted. No network from subagent to non-allowlisted hosts. Files written by subagent are inspected by the parent before being applied to the real repo.
- **Cost control:** the parent agent must estimate subagent cost before dispatching. If estimated cost > 50K tokens, require Captain confirmation.
- **Audit:** every subagent dispatch is logged to `data/subagent_log.db` (SQLite, append-only): timestamp, task description, subagent type, token count, exit status, result summary.
- **Bypass:** the `subagent_dispatch` tool is always available to the agent. Captain can disable it via env: `AUREON_SUBAGENT_DISABLED=1` (for tests, debugging).

## Read these on session start (in order)

1. `CLAUDE.md` — project context
2. `CONTEXT.md` — stack, infra, decisions
3. `tasks/DEVLOG.md` (last 2 entries) — current world state
4. `tasks/todo.md` — current phase status
5. This file (the kickoff)
6. `~/.openclaw/workspace/MEMORY.md` §Olympus, §Coding Agents, §delegate_task
7. `skill_loader.py` — existing tool integration pattern (mirror this shape)
8. `agent_runtime.py` — where the tool is plugged into the ReAct loop

## Your role

You are adding a new tool to the agent's tool registry. Mirror the pattern in `skill_loader.py` (synthesized tool + execute function), but the execution model is different — it shells out to a subprocess instead of running inline. Self-improvement loop: log every dispatch to `workspace/tasks/lessons.md` if the subagent fails or returns surprising results.

---

## 6 sub-tasks (in order)

### Sub-task 1: Subagent backend abstraction (60 min)

Define the interface for any subagent backend (claude-code, opencode, future):

- [ ] Create `subagent/` package:
  - `subagent/__init__.py`
  - `subagent/base.py` — `SubagentBackend` ABC with:
    ```python
    class SubagentBackend(ABC):
        @abstractmethod
        async def dispatch(self, task: SubagentTask) -> SubagentResult: ...
    ```
  - `subagent/claude_code.py` — `ClaudeCodeBackend(SubagentBackend)` that wraps `claude` CLI
  - `subagent/task.py` — `SubagentTask` dataclass: `task_id`, `prompt`, `workdir`, `timeout_sec`, `model`, `allowed_paths`
  - `subagent/result.py` — `SubagentResult` dataclass: `task_id`, `exit_code`, `output_text`, `output_files`, `token_count`, `duration_sec`
- [ ] `ClaudeCodeBackend.dispatch()`:
  - Build the CLI invocation: `claude -p "<prompt>" --output-format json --max-turns 10 --workdir <workdir>`
  - Stream stdout, capture all output
  - Enforce timeout via `asyncio.wait_for` around `subprocess.communicate()`
  - On timeout: kill the subprocess, return `SubagentResult(exit_code=-1, output_text="timed out")`
  - Parse the JSON output (or fallback to raw text if format fails)
- [ ] Tests in `tests/test_subagent_backends.py`:
  - Mock subprocess, verify CLI args are correct
  - Verify timeout kills the subprocess
  - Verify JSON parsing falls back to raw text on bad output
  - Use a real `claude --version` to verify the binary is on PATH (or skip with `@pytest.mark.skipif`)

### Sub-task 2: Sandbox + audit logging (60 min)

Sandbox every subagent dispatch. Log every dispatch to SQLite:

- [ ] Create `subagent/sandbox.py`:
  - `class Sandbox: __init__(self, source_repo_path: Path) -> None`
  - `async def create(self) -> Path:` returns `/tmp/aureon-subagent-<uuid8>/`
  - Inside: symlink `source_repo_path` as read-only (`os.symlink` + `chmod 0o555` on the symlink target, or use `bindfs` if available; fall back to `chmod -R a-w` if bindfs missing)
  - `async def cleanup(self) -> None:` removes the temp dir
  - Captain's rule: no `0.0.0.0` binds, no writes to `~/.ssh/`, no writes to `~/.openclaw/openclaw.json` — the sandbox is just a workdir, not a full container
- [ ] Create `data/subagent_log.db` schema:
  - Table `dispatch_log`: `id INTEGER PRIMARY KEY, task_id TEXT, created_at TEXT, task_description TEXT, backend TEXT, token_count INTEGER, exit_code INTEGER, duration_sec REAL, result_summary TEXT`
  - On every dispatch: INSERT before the call, UPDATE with results after
  - Index on `created_at` for time-based queries
- [ ] Tests in `tests/test_subagent_sandbox.py`:
  - Sandbox creates temp dir with symlink
  - Cleanup removes temp dir
  - Audit log writes a row, then updates it with results
  - `aureon-agent-doctor` checks: subagent_log.db is writable, schema is intact

### Sub-task 3: `delegate_task` tool integration (90 min)

Wire the tool into the agent's registry. This is the bulk of the work.

- [ ] Add a synthesized tool (like `skill_loader.py` does for prose skills):
  - Name: `delegate_task`
  - Description (for the LLM): "Spawn a subagent to handle a long-running or parallel task. The subagent runs in an isolated sandbox, returns a markdown result. Use for: research, code review, audit, refactor, test generation. NOT for: trivial single-step tasks."
  - Schema:
    ```json
    {
      "name": "delegate_task",
      "description": "...",
      "input_schema": {
        "type": "object",
        "properties": {
          "task_description": {"type": "string", "description": "What the subagent should do. Be specific."},
          "backend": {"type": "string", "enum": ["claude-code", "opencode"], "default": "claude-code"},
          "model": {"type": "string", "enum": ["sonnet", "opus", "haiku"], "default": "sonnet"},
          "timeout_sec": {"type": "integer", "default": 300, "maximum": 600},
          "files_to_inspect": {"type": "array", "items": {"type": "string"}, "description": "Files the subagent should read first"}
        },
        "required": ["task_description"]
      }
    }
    ```
  - Execute function:
    1. Build `SubagentTask` from the input
    2. Create the sandbox
    3. Write `files_to_inspect` to a `briefing.md` file in the sandbox (so the subagent sees them on startup)
    4. Call `backend.dispatch(task)` — returns `SubagentResult`
    5. Log to `subagent_log.db`
    6. Cleanup sandbox
    7. Return `{"output": result.output_text, "files": result.output_files, "token_count": result.token_count, "exit_code": result.exit_code}`
- [ ] Cost-control check BEFORE dispatching:
  - Estimate token count: `len(task_description) / 4 + sum(len(f) for f in files_to_inspect) / 4`
  - If > 50K, return `{"error": "estimated cost > 50K tokens, ask Captain to confirm"}` and do NOT dispatch
- [ ] Register the tool in `agent_runtime.py` alongside the existing 8 doctrine skills (do NOT add as a 9th skill — keep skills and subagent dispatch as separate tool namespaces)
- [ ] Tests in `tests/test_delegate_task_tool.py`:
  - Mock backend, verify execute() calls dispatch with correct args
  - Verify cost-control blocks > 50K
  - Verify sandbox is created + cleaned up
  - Verify audit log row is written
  - Verify timeout kills the subagent
  - Verify the tool is in the agent's tool registry

### Sub-task 4: Channel integration (30 min)

Make sure the subagent result flows back through the channel correctly:

- [ ] When `delegate_task` returns, the parent agent's response should:
  - Mention that a subagent was used
  - Quote the subagent's result
  - Link to the audit log entry (Captain can see the dispatch in `data/subagent_log.db`)
- [ ] Telegram/Discord streaming: don't stream subagent output to the channel (it's a single big result, not a stream). Wait for completion, then send a single edit with the result.
- [ ] Tests in `tests/test_subagent_channel.py`:
  - Mock channel, send a 3-step task, verify the response includes the subagent result + audit link

### Sub-task 5: Captain-facing affordances (30 min)

- [ ] Add `aureon-agent subagent-log --last 10` subcommand to `aureon_agent/cli.py` — shows recent dispatches from `data/subagent_log.db`
- [ ] Add `aureon-agent subagent-log --since 1h` filter
- [ ] Add `aureon-agent doctor` check: subagent_log.db is readable, last dispatch < 30 days old
- [ ] Update `CLAUDE.md` Commands section with the new subcommand

### Sub-task 6: Tests + live verification (60 min)

- [ ] `pytest tests/` — all tests pass (15+ tests now)
- [ ] `python tests/smoke.py` — all checks pass
- [ ] `aureon-agent-doctor` — 6+/8 green, 0 errors
- [ ] Live test: send a Telegram message that triggers `delegate_task`:
  - "do a code review of main.py" — should spawn claude-code, return review result
  - "research Ollama's 200K vs 1M context models" — should spawn claude-code, return research result
- [ ] Verify the audit log row is correct (`aureon-agent subagent-log --last 1`)

## Acceptance criteria

- [ ] `delegate_task` tool is in the agent's tool registry, accepts `task_description` + optional `backend`/`model`/`timeout_sec`/`files_to_inspect`
- [ ] `claude-code` backend dispatches via subprocess with timeout + cleanup
- [ ] Sandbox creates a temp dir with read-only source, cleans up on success/failure
- [ ] Audit log captures every dispatch in `data/subagent_log.db`
- [ ] Cost control refuses to dispatch if estimated tokens > 50K
- [ ] Subagent result is included in the parent agent's response
- [ ] `aureon-agent subagent-log --last 10` shows recent dispatches
- [ ] `aureon-agent doctor` checks subagent_log.db
- [ ] Live test: 2 different subagent tasks run end-to-end via Telegram
- [ ] All existing tests still pass (no regressions)
- [ ] PR opened to `dev`, DEVLOG entry written, todo.md updated

## Out of scope (v1)

- Multiple concurrent subagents (FIFO queue is enough for v1)
- Subagent-of-subagent (recursive dispatch)
- Cross-backend fallback (if claude-code fails, don't auto-retry with opencode)
- Subagent cost dashboard / telemetry UI
- Persistent subagent sessions (subagents are stateless, fire-and-forget)
- Per-channel subagent policy (Discord server gets more autonomy than Telegram DM)
- Streaming subagent output to channel (v1 is wait-for-completion)

## Full spec references

- This file: `tasks/kickoff-subagent-dispatch.md`
- Doctrine: `~/.openclaw/workspace/MEMORY.md` §Olympus, §Coding Agents, §delegate_task
- Tool pattern to mirror: `skill_loader.py`
- ReAct loop: `agent_runtime.py`
