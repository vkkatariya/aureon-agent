# Task: Plan-node hard block (v2)

**Branch:** `feat/aureon-agent-plan-node-hard-block` (off `dev`)
**Mode:** Builder
**Complexity:** Small — soft warning already exists in `plan_node.py`, promote to hard block + new heuristics
**Estimated effort:** 1 evening, ~150-200 LoC + tests

---

## Setup

- **Project:** `aureon-agent`
- **Path on athena:** `~/dev-shared/projects/aureon-agent/`
- **Working directory:** this repo
- **Active branch:** `feat/aureon-agent-plan-node-hard-block` (off `dev`)
- **Session name:** `[aureon-agent]-local` (you're the local session, persistent tmux)

## What this is

Promote the existing soft-warning plan-node check (currently in `plan_node.py`, only logs a warning) to a **hard block**: when the agent receives a task that implies 3+ steps and the user hasn't written a plan, the agent must refuse to start work and ask Captain to write one first. The plan goes in `tasks/todo.md` (project-level) or `~/.openclaw/workspace/tasks/todo.md` (Captain's) — both are valid.

This is the scope-discipline gate that prevents the 4-hour security-model rebuild lesson from 2026-06-16. It catches the "I'll just add this one thing" pattern before it cascades.

## Reference docs (read before designing)

- **`~/.openclaw/workspace/MEMORY.md`** §"Per-Project AGENTS.md Contract" — the 6-rule contract, rule #1 is "Plan Node"
- **`~/.openclaw/workspace/MEMORY.md`** §"🦾 Lessons from 2026-06-16/17" — the scope-creep incident that motivated this
- **Existing soft warning:** `plan_node.py` in this repo — already does keyword-based step counting + warns
- **Existing `tasks/todo.md` plan format:** lines starting with `- [ ]` (unchecked items = planned, not yet done)
- **Per-project AGENTS.md contract:** rule #1 (Plan Node for 3+ step tasks before any code)

## Decisions confirmed with user (2026-07-13)

- **Threshold:** 3+ steps triggers the block. 1-2 steps proceed with just a soft warning.
- **Plan location:** Either `tasks/todo.md` (this project) OR `~/.openclaw/workspace/tasks/todo.md` (Captain's master) — both count. Agent should prefer the project-level file when the request is project-scoped.
- **Bypass:** Captain can override with a magic phrase (`just do it`, `skip the plan`, `simple task`) — agent should accept this but log it as a flag for the post-session audit. Don't make bypass hard to use; the goal is to catch *accidental* scope creep, not to annoy deliberate work.
- **Subagent work:** subagent results don't trigger the block (subagents are already scoped by their kickoff prompt). The block is for the top-level user request.
- **Read-only operations:** don't trigger the block (e.g. "show me the doctor output" — 1 step, not planning-worthy).
- **Plan-node check happens in `agent_runtime.py` BEFORE the first ReAct iteration**, not at the channel layer. Channels stay simple; planning lives in the runtime.
- **Failure mode:** if the plan file is unwritable, the block fails open (proceeds with a warning) — never strand Captain with an unfixable block.

## Read these on session start (in order)

1. `CLAUDE.md` — project context
2. `CONTEXT.md` — stack, infra, decisions
3. `tasks/DEVLOG.md` (last 2 entries) — current world state
4. `tasks/todo.md` — current phase status
5. This file (the kickoff)
6. `~/.openclaw/workspace/MEMORY.md` §Olympus + §Lessons from 2026-06-16/17
7. `plan_node.py` — existing soft check (read first to know what to replace)

## Your role

You are modifying the agent runtime to enforce a scope-discipline gate. Use the per-project AGENTS.md contract as the design spec — this is rule #1 ("Plan Node"). Self-improvement loop: when the plan-node check fires spuriously or misses a real case, append to `workspace/tasks/lessons.md` (numbered L-NNN).

---

## 4 sub-tasks (in order)

### Sub-task 1: Step-counting heuristic (60 min)

The current `plan_node.py` has a keyword-based step counter. Improve it:

- [ ] Read `plan_node.py` current state
- [ ] Replace simple keyword regex with a structured step detector:
  - Count imperative verbs ("build", "create", "fix", "add", "remove", "update", "implement", "deploy", "test", "write", "refactor", "migrate") — each match = 1 step
  - Count conjunctions ("and", "then", "also", "plus", "after that", "next") between verbs
  - Count file paths (e.g. `foo.py`, `path/to/file.md`) — each unique = 1 step
  - Count URLs / endpoints (e.g. `https://...`, `localhost:8080`) — each = 1 step
  - If step count >= 3, the task needs a plan
- [ ] Read-only check: requests with "show", "list", "display", "what is", "how many" don't need a plan regardless of step count
- [ ] Confidence: heuristic is heuristic. Log a debug-level note when the step count is borderline (2-3).
- [ ] Tests in `tests/test_plan_node.py`:
  - "fix the typo" → 1 step, no plan needed
  - "add a /health endpoint and update the README and run the tests" → 3 steps, plan needed
  - "show me the doctor output" → 1 step, no plan needed (read-only)
  - "build a new MCP server, test it, deploy it, document it" → 4 steps, plan needed

### Sub-task 2: Plan detection (45 min)

When a plan is needed, the agent must check if one exists before proceeding:

- [ ] Read `tasks/todo.md` AND `~/.openclaw/workspace/tasks/todo.md` (whichever exists)
- [ ] Count `- [ ]` lines (unchecked items) — if >= 1, a plan exists
- [ ] If `- [ ]` count = 0 in both files, the plan is missing (block)
- [ ] If neither file exists, treat as missing (block)
- [ ] For a fresh `tasks/todo.md`, even a one-line plan like `- [ ] fix the typo` counts (don't gatekeep on plan quality)
- [ ] Bypass phrases: match against the user message with a case-insensitive regex:
  - `r"\b(just do it|skip the plan|simple task|quick fix|trivial)\b"`
  - When matched, proceed but log `WARNING: plan-node bypassed by user phrase` at WARN level
- [ ] Tests in `tests/test_plan_node.py`:
  - When plan exists, no block
  - When plan missing, block with clear message
  - When bypass phrase used, proceed + log
  - When both todo files exist, prefer project-level plan

### Sub-task 3: Hard block in `agent_runtime.py` (45 min)

Wire the check into the runtime. Currently `plan_node.py` only logs; we need to **block**:

- [ ] Add a new function in `plan_node.py`: `async def require_plan(user_message: str) -> tuple[bool, str]` — returns `(ok, reason)`. `ok=False` means block.
- [ ] Call it at the top of `AgentRuntime.handle_message()` BEFORE the first ReAct iteration
- [ ] If `require_plan` returns `ok=False`, return a structured response:
  - Telegram: "🛑 Plan needed. This task has 3+ steps but `tasks/todo.md` has no `- [ ]` items. Add a plan (one line is enough) or say 'just do it' to bypass."
  - Discord: same wording
  - The block response uses the existing channel adapter, no special-casing
- [ ] Log the block at INFO level with: `plan-node-blocked` event, step count, file paths detected, bypass status
- [ ] Failure mode: if `require_plan` raises (e.g. file system error), log ERROR and proceed with the work (fail open, never strand the user)
- [ ] Tests in `tests/test_agent_loop.py` (or new `tests/test_plan_node_integration.py`):
  - "fix the typo" → proceeds, no block
  - "build X, test Y, deploy Z" without plan → blocked, returns clear message
  - "build X, test Y, deploy Z" with `tasks/todo.md` having `- [ ]` items → proceeds
  - "build X, test Y, deploy Z, just do it" → proceeds + bypass log
  - file system error on read → proceeds + ERROR log

### Sub-task 4: Telemetry + test coverage (30 min)

- [ ] Add a counter to the runtime: `plan_node_blocks_total` — incremented on each block, logged every 100 messages
- [ ] Update `aureon-agent-doctor` to check that the plan-node function is importable + can be called with a sample message (smoke test for the check itself)
- [ ] Update `CLAUDE.md` §Hard constraints with the new block rule
- [ ] Update `tasks/todo.md` Phase 6: mark this item `[x]` with PR link
- [ ] Tests pass: `pytest tests/` (should be 8+ tests now), `python tests/smoke.py`
- [ ] Live test: send a 3-step task to the live bot, verify it blocks with the expected message

## Acceptance criteria

- [ ] Agent blocks 3+ step tasks without a plan, with a clear Telegram/Discord message
- [ ] Agent proceeds when a plan exists in `tasks/todo.md` or `~/.openclaw/workspace/tasks/todo.md`
- [ ] Agent proceeds when a bypass phrase is used, with a WARN log
- [ ] Read-only requests (show/list/display) never trigger the block
- [ ] Step counter catches: 3+ imperative verbs, 3+ file paths, 3+ URLs
- [ ] Plan file read errors fail open (proceed with ERROR log, never strand user)
- [ ] `aureon-agent-doctor` passes on live system
- [ ] `python tests/smoke.py` passes
- [ ] `pytest tests/` passes (8+ tests)
- [ ] PR opened to `dev`, DEVLOG entry written, todo.md updated

## Out of scope (v1)

- Plan quality checking (does the plan actually cover the steps?) — that's LLM-as-judge, deferred to v2
- Multi-file plan mode (`tasks/plan.md` separate from `tasks/todo.md`) — single file is enough
- Plan-node config in `.env` (e.g. threshold) — hardcoded 3 for v1
- Bypass audit log file — just the runtime log for now
- Plan editor (Telegram message → write to `tasks/todo.md`) — would be nice but separate task

## Full spec references

- This file: `tasks/kickoff-plan-node-hard-block.md`
- 6-rule contract: `~/.openclaw/workspace/MEMORY.md` §"Per-Project AGENTS.md Contract"
- Scope discipline lesson: `~/.openclaw/workspace/MEMORY.md` §"🦾 Lessons from 2026-06-16/17"
- Existing soft check: `plan_node.py` in this repo
