# Task: Add Tier 2 tools (todo, clarify) to aureon-agent

**Branch:** `feat/aureon-agent-tier2-tools` (off `dev`)
**Mode:** Builder
**Complexity:** Small-Medium — 2 tools, but `clarify` requires ReAct pause/resume
**Estimated effort:** 1-2 evenings, ~300-400 LoC + tests

---

## Setup

- **Project:** `aureon-agent`
- **Path on athena:** `~/dev-shared/projects/aureon-agent/`
- **Working directory:** this repo
- **Active branch:** `feat/aureon-agent-tier2-tools` (off `dev`)
- **Session name:** `[aureon-agent]-local` (you're the local session, persistent tmux)

## What this is

Add 2 small-but-highly-leverage tools to the agent's tool registry, mirroring the shapes Hermes uses for the same capabilities:

- **`todo`** — read/write/manage the project's `tasks/todo.md` plan file. Pairs with the plan-node hard block (already spec'd in `tasks/kickoff-plan-node-hard-block.md`).
- **`clarify`** — pause the ReAct loop, ask Captain a clarifying question, resume with the answer. Pairs with the plan-node block too (when the agent doesn't know what to do, ask instead of guessing).

These are smaller than Tier 1 (terminal + file + web) but solve a key UX problem: the agent currently has no way to maintain its own plan or ask before doing something ambiguous. With these two tools + the plan-node hard block, the agent has a closed loop for "3+ step task → block → read todo.md → ask Captain for plan → resume".

## Reference docs (read before designing)

- **`skill_loader.py`** — the synthesized tool pattern. Mirror it.
- **`agent_runtime.py`** — ReAct loop, where the tools plug in. **Critical: `clarify` requires pausing the loop, which is a non-trivial change to the runtime.**
- **`context_builder.py`** — assembles system prompt. The `todo` tool's reads may go into the prompt.
- **`tasks/todo.md`** — the existing plan file format (`- [ ]` for unchecked items)
- **Plan-node kickoff:** `tasks/kickoff-plan-node-hard-block.md` — the consumer of these tools
- **Subagent kickoff:** `tasks/kickoff-subagent-dispatch.md` — the subagent kickoff also needs a `todo` for its own scope

## Decisions confirmed with user (2026-07-13)

### `todo` tool

- **3 sub-tools** in the LLM registry:
  - `todo_read(path: str = "tasks/todo.md") -> str` — returns the current plan file content
  - `todo_write(path: str, content: str, append: bool = False) -> str` — overwrites or appends to the plan file
  - `todo_add(path: str, item: str) -> str` — adds a single `- [ ]` line at the end of the file
- **Default path:** `tasks/todo.md` (the project's plan file). Captain can specify a different file per call.
- **Path validation:** the file must be in `~/dev-shared/projects/` (no writing to `~/.openclaw/`). Follows the same allowlist as Tier 1 `file` tool.
- **Format:** the agent writes Markdown. No JSON, no structured data. The file is human-readable.
- **Append vs overwrite:** the `append` flag defaults to False (safer — overwrite is explicit).
- **Concurrent writes:** last-write-wins. No file locking for v1 (low contention since the agent is single-threaded per session).

### `clarify` tool

- **Schema:**
  ```json
  {
    "name": "clarify",
    "description": "Pause the current task and ask Captain a clarifying question. Use when: 3+ step task with ambiguous scope, destructive action unclear, conflicting requirements, missing info. Returns Captain's reply (string) or empty string if timeout.",
    "input_schema": {
      "type": "object",
      "properties": {
        "question": {"type": "string", "description": "The question to ask Captain. Be specific. Include context, what you're trying to do, and what info you need."},
        "options": {"type": "array", "items": {"type": "string"}, "description": "Optional: 2-5 multiple-choice options. If provided, Captain can reply with the number/letter. If empty, Captain replies with free-form text."},
        "timeout_sec": {"type": "integer", "default": 300, "maximum": 1800, "description": "How long to wait for Captain's reply before timing out (default 5 min, max 30 min)"}
      },
      "required": ["question"]
    }
  }
  ```
- **Behavior:**
  1. Agent hits the tool during a ReAct iteration
  2. Tool sends a `✋` message to Telegram/Discord with the question + options (if any)
  3. Tool waits for Captain's reply (up to `timeout_sec`)
  4. On reply: returns the answer string to the agent
  5. On timeout: returns empty string + logs WARN. Agent should treat as "no answer" and either proceed cautiously or block.
- **One-clarify-per-iteration:** the runtime only allows ONE `clarify` call per `handle_message()` invocation. If the agent tries to clarify twice in a row, the second one fails with an error ("already asked a clarifying question this turn, wait for the next user message"). Prevents infinite clarification loops.
- **Per-session cap:** max 3 `clarify` calls per `handle_message()`. After 3, the tool returns error. Forces the agent to either commit or fail.
- **The "user reply" mechanism:** when Captain replies to a clarification, the channel adapter treats it as a regular user message. The reply needs to be paired with the pending clarification so the runtime knows which question is being answered. Implementation: a `pending_clarifications: dict[session_id, question_metadata]` in memory. When a message arrives, check if there's a pending clarification for that session; if yes, route to the tool waiter, not the normal handler.
- **Message threading:** the question message gets a marker (`clarification_id`) in its reply-to. Captain's reply must echo this marker (or be a plain reply to the channel). For v1, plain reply is fine.

### Cross-cutting

- **Both tools share `WorkspaceBoundTool` base class** from Tier 1 (no duplication).
- **Both tools log to `data/tool_log.db`** (same audit log as Tier 1).
- **Channel adapter change:** the Telegram/Discord adapter must distinguish between "user reply" (normal) and "user reply to clarification" (route to waiter). Add a `pending_clarifications` registry to the router.

## Read these on session start (in order)

1. `CLAUDE.md` — project context
2. `CONTEXT.md` — stack, infra, decisions
3. `tasks/DEVLOG.md` (last 2 entries) — current world state
4. `tasks/todo.md` — current phase status
5. This file (the kickoff)
6. `tasks/kickoff-tier1-tools.md` — sibling kickoff (the `WorkspaceBoundTool` base is defined there)
7. `agent_runtime.py` — the ReAct loop, focus on where to plug in pause/resume
8. `channels/router.py` + `channels/telegram.py` — where the routing logic lives

## Your role

You are adding 2 small tools. The `todo` tool is straightforward (file read/write). The `clarify` tool requires **changing the ReAct loop to support pause-and-resume** — that's the tricky part. Mirror the synthesized tool pattern from `skill_loader.py`. Use the `WorkspaceBoundTool` base from Tier 1 (don't redefine). Self-improvement loop: log every `clarify` timeout to `workspace/tasks/lessons.md` so we can tune the default.

---

## 4 sub-tasks (in order)

### Sub-task 1: `todo` tool (60 min)

Three sub-tools, simple file operations.

- [ ] New: `aureon_agent/tools/todo.py`
- [ ] `class TodoTool(WorkspaceBoundTool)` with 3 sub-tools:
  - `todo_read(path: str = "tasks/todo.md") -> str`:
    - Validate `path` is under `~/dev-shared/projects/` (Tier 1's `validate_path` with `write=False` since this is a read)
    - Read file content, return as string. If file doesn't exist, return "" + note "(plan file does not exist yet — use todo_add to create)"
  - `todo_write(path: str, content: str, append: bool = False) -> str`:
    - Validate `path` (write=True this time)
    - If `append=True`: open in append mode, write `content` + newline
    - If `append=False`: open in write mode (overwrite), write `content`
    - Return success message with line count
  - `todo_add(path: str, item: str) -> str`:
    - Validate `path`
    - Append `- [ ] {item}\n` to the file
    - Return success: "added: - [ ] {item}"
- [ ] Synthesized tool schema (3 separate schemas, dispatch on `action` field)
- [ ] Tests in `tests/test_tools_todo.py`:
  - `todo_read("tasks/todo.md")` on existing file → returns content
  - `todo_read("nonexistent.md")` → returns "" + note
  - `todo_read("/etc/passwd")` → WorkspaceViolation
  - `todo_write("tasks/todo.md", "new content", append=False)` → overwrites
  - `todo_write("tasks/todo.md", "more", append=True)` → appends
  - `todo_write("~/.openclaw/workspace/SOUL.md", "...")` → rejected (read-only)
  - `todo_add("tasks/todo.md", "fix the bug")` → appends `- [ ] fix the bug`

### Sub-task 2: `clarify` tool — runtime pause/resume (90 min)

The tricky part: the ReAct loop must support pausing when the agent calls `clarify`, waiting for Captain's reply, then resuming with the reply in the LLM's context.

- [ ] New: `aureon_agent/tools/clarify.py`
- [ ] Add to `agent_runtime.py`:
  - On `handle_message()` entry, initialize a `pending_clarifications: dict[str, asyncio.Future]` keyed by `clarification_id`
  - On tool dispatch: if the tool is `clarify`, send the question via the channel, register a `Future`, and `await` it
  - On user message arrival (in `channels/router.py`): check if `pending_clarifications` has a future for this `session_id`; if yes, resolve the future with the user's reply text, do NOT process as a new turn
  - If no pending clarification: process normally as a new user turn
- [ ] `class ClarifyTool` (no `WorkspaceBoundTool` inheritance — clarify is a channel tool, not a workspace tool):
  - Synthesized tool schema (see Decisions)
  - `async def execute(self, tool_input: dict, context: dict) -> dict`:
    1. Check per-iteration cap: if `len(self.iteration_clarifications) >= 1`, return `{"error": "already asked a clarifying question this iteration"}`
    2. Check per-session cap: if `len(self.session_clarifications) >= 3`, return `{"error": "max 3 clarifying questions per message, must commit or fail"}`
    3. Generate `clarification_id = uuid4().hex[:8]`
    4. Format the message: `✋ Clarification needed:\n\n{question}\n\n{options as numbered list if provided}\n\n_Reply to this message to answer._`
    5. Send via `channel.send(session_id, message, reply_markup=None)` — Telegram's `sendMessage` with no special markup
    6. Register the future in `runtime.pending_clarifications[clarification_id]`
    7. `await asyncio.wait_for(future, timeout=timeout_sec)`
    8. On reply: return `{"answer": reply_text, "clarification_id": clarification_id}`
    9. On timeout: return `{"answer": "", "clarification_id": clarification_id, "timeout": true}` (WARN logged)
- [ ] Channel router change in `channels/router.py`:
  - On incoming message: check `runtime.pending_clarifications` for any `Future` for this `session_id`
  - If found: resolve the future, do NOT process as a new turn
  - If not found: process normally
- [ ] Tests in `tests/test_tools_clarify.py`:
  - Mock channel + asyncio, verify the question is sent
  - Verify timeout returns empty string + WARN logged
  - Verify second `clarify` in same iteration fails
  - Verify 4th `clarify` in same session fails
  - Verify the channel router routes the reply correctly to the future
  - End-to-end: agent calls clarify, channel sends question, user replies, agent receives answer

### Sub-task 3: Tool registry integration (30 min)

Wire the 2 new tools into the runtime.

- [ ] Add to `agent_runtime.py`:
  - On `__init__`: create instances of `TodoTool` (with workspace allowlist) and `ClarifyTool` (with channel reference + pending-clarifications registry)
  - In the tool registration: add the synthesized tool schemas to the existing skill tool list
  - In the tool dispatch: handle `todo_read`/`todo_write`/`todo_add` and `clarify`
- [ ] Per-channel tool policy: same as Tier 1 (Telegram/Discord DM = full, server/group = restricted in v2)
- [ ] Tests in `tests/test_agent_loop.py`:
  - All 2 new tools are in the agent's tool list when initialized
  - Tool dispatch routes correctly by name
  - `clarify` is gated by the per-iteration + per-session caps

### Sub-task 4: Telemetry + doctor + docs (30 min)

- [ ] Add `aureon-agent clarify-log --last 10` subcommand to `aureon_agent/cli.py` — shows recent `clarify` calls (read from `data/tool_log.db` filtered by `tool_name='clarify'`)
- [ ] Add `aureon-agent doctor` checks:
  - `data/tool_log.db` is readable (already exists from Tier 1, but verify)
  - workspace allowlist paths exist (already exists from Tier 1)
  - `clarify_log.db` (if separate) is readable — or just use tool_log filter
- [ ] Update `CLAUDE.md` Commands section with new subcommand
- [ ] Update `CONTEXT.md` Architecture section to list the 2 new tools
- [ ] Update `README.md` "What it does" section to mention `todo` and `clarify`
- [ ] Add a `docs/tools.md` design doc (or extend the Tier 1 one) with both tiers

## Acceptance criteria

- [ ] `todo` tool: 3 sub-tools (read/write/add) with workspace allowlist
- [ ] `todo` tool: respects `~/dev-shared/projects/` (rw) + `~/.openclaw/workspace/` (ro)
- [ ] `clarify` tool: sends the question via channel, waits for reply, returns the answer
- [ ] `clarify` tool: 1-clarify-per-iteration cap enforced
- [ ] `clarify` tool: 3-clarify-per-session cap enforced
- [ ] `clarify` tool: timeout returns empty string + WARN log
- [ ] Channel router: routes user replies to pending clarifications, not new turns
- [ ] Both tools log to `data/tool_log.db`
- [ ] `aureon-agent clarify-log --last 10` shows recent clarifications
- [ ] `aureon-agent doctor` checks workspace allowlist
- [ ] All existing tests still pass (no regressions)
- [ ] Live test via Telegram:
  - "show me the current plan" → `todo_read` returns `tasks/todo.md` content
  - "add 'fix the bug' to the plan" → `todo_add` appends a `- [ ]` line
  - "build a thing that does X" (ambiguous) → `clarify` sends a question, Captain replies, agent continues
- [ ] PR opened to `dev`, DEVLOG entry written, todo.md updated

## Out of scope (v1, future work)

- Subagent `todo` (subagents can have their own plan files — `tasks/<subagent_id>.todo.md`)
- Rich `clarify` UIs (Telegram inline keyboards, Discord buttons) — v1 is plain text
- `clarify` with file attachments (e.g. "look at this file then answer") — v2
- `clarify` chain (one question leads to another) — already capped at 1-per-iteration + 3-per-session
- Multi-party clarifications (asking in a group chat) — out of scope, Captain-DM only
- Persistent clarification state across bot restarts (in-memory only for v1)
- `todo` history / archive (every edit is permanent, no undo)
- `todo` schema validation (the file is just Markdown, the agent writes whatever it wants)
- `clarify` for proactive check-ins (agent asks "is this still what you want?") — out of scope

## Full spec references

- This file: `tasks/kickoff-tier2-tools.md`
- Tier 1 sibling: `tasks/kickoff-tier1-tools.md` (the `WorkspaceBoundTool` base is defined there)
- Tool pattern: `skill_loader.py`
- ReAct loop: `agent_runtime.py` (focus on pause/resume for `clarify`)
- Channel router: `channels/router.py`
- Plan-node consumer: `tasks/kickoff-plan-node-hard-block.md`
- Subagent consumer: `tasks/kickoff-subagent-dispatch.md` (subagents also need a `todo`)
