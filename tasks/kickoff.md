# aureon-agent: Combined Phase 6 + 6.5 Kickoff

**Project:** aureon-agent
**Path on athena:** `~/dev-shared/projects/aureon-agent/`
**Branch model:** each work item gets its own `feat/<item>` branch off `dev`
**Mode:** Builder
**Estimated total effort:** 4-6 evenings across all 5 work items, ~1,500-2,000 LoC + tests
**Session name pattern:** `[aureon-agent]-local` (you're the local session, persistent tmux)

---

## What this is

Five remaining work items, ordered by leverage. Each is a self-contained kickoff. Dispatch one at a time, in priority order. Each lands as its own PR. After all 5 land, aureon-agent is feature-complete against the Hermes comparison and ready for the next phase (MCP, subagent of agents, etc).

| # | Work item | Sub-tasks | LoC | PR | Kickoff section |
|---|---|---|---|---|---|
| 1 | Tier 1 tools (terminal, file, web) | 6 | ~700 | Tier 1 | [§ 1](#1-tier-1-tools-terminal-file-web) |
| 2 | Tier 2 tools (todo, clarify) | 4 | ~400 | Tier 2 | [§ 2](#2-tier-2-tools-todo-clarify) |
| 3 | Subagent dispatch (delegate_task) | 6 | ~500 | Subagent | [§ 3](#3-subagent-dispatch-via-delegate_task) |
| 4 | Plan-node hard block (v2) | 4 | ~200 | Plan-node | [§ 4](#4-plan-node-hard-block-v2) |
| 5 | Session compaction — already shipped (PR #16) | 4 | ~600 | #16 ✅ | (reference only) |

> **Reference docs that apply to ALL work items:**
> - `CLAUDE.md` — project context
> - `CONTEXT.md` — stack, infra, decisions
> - `tasks/DEVLOG.md` (last 2 entries) — current world state
> - `tasks/todo.md` — current phase status
> - `~/.openclaw/workspace/MEMORY.md` §Olympus + §🦾 Lessons from 2026-06-16/17 — channel-policy + scope-discipline doctrine
> - Per-project `AGENTS.md` — 6-rule contract (Plan Node, Subagent Strategy, Self-Improvement Loop, Verification, Demand Elegance, Autonomous Bug Fixing)
>
> **Your role (applies to all 5 work items):**
> - Follow the per-project AGENTS.md 6-rule contract
> - Self-improvement loop: log every correction to `workspace/tasks/lessons.md` (numbered L-NNN)
> - Verification before done: tests pass, doctor passes, live test via Telegram
> - Don't add scope beyond what's asked
> - When in doubt, ask Captain

---

## 1. Tier 1 tools (terminal, file, web)

**Branch:** `feat/aureon-agent-tier1-tools` (off `dev`)
**Complexity:** Non-trivial — 3 new tools + safety rails + workspace allowlist
**Estimated effort:** 2-3 evenings, ~700 LoC + tests

### What this is

Add 3 high-leverage tools to the agent's tool registry, mirroring the shapes Hermes uses for the same capabilities. Once shipped, the agent can run shell commands, manipulate files in approved workspaces, and look things up on the web.

### Decisions confirmed with user (2026-07-13)

**Terminal tool:**
- Allowlist: `ls, cat, grep, find, git status/log/diff, pwd, echo, date, whoami, hostname, df, du, wc, head, tail, which, env` — auto-run.
- Destructive commands (`rm, mv, chmod, kill, pkill, systemctl stop, drop, delete, truncate, dd, >, >>, mkfs, fdisk`) — ALWAYS ask Captain.
- 30s timeout default, configurable per call. Output capture: stdout, stderr, exit code. Truncate to 50KB.
- `subprocess.run(args, ...)` with a list, never `shell=True` (no injection).
- No interactive commands (`vim`, `less`, `top` — return error, not hang).

**File tool:**
- 3 sub-tools: `read_file(path, max_lines=500)`, `write_file(path, content)`, `list_dir(path, pattern="*")`.
- Allowlist: `~/dev-shared/projects/` (rw), `~/.openclaw/workspace/` (ro). Reject everything else.
- No symlink following outside allowlist. No binary writes (`.png, .jpg, .pdf, .exe, .so, .zip, .tar, .gz, .bin`).
- UTF-8 only. Overwrite of existing file asks Captain.

**Web tool:**
- 2 sub-tools: `web_search(query, max_results=5)` → `[{title, url, snippet}]`, `web_fetch(url, max_chars=5000)` → markdown/text.
- v1 backend: DuckDuckGo HTML (`https://html.duckduckgo.com/html/?q=...`) for search, `httpx` GET for fetch. No API key.
- v2 backend: Brave Search API when `BRAVE_API_KEY` env is set.
- Respects robots.txt by default. Captain can disable with `AUREON_WEB_IGNORE_ROBOTS=1` (logged at WARN).
- User-Agent: `aureon-agent/0.1 (+https://github.com/vkkatariya/aureon-agent)`.
- Timeout: 10s for search, 30s for fetch.

**Cross-cutting:**
- Common base class `WorkspaceBoundTool` enforces allowlist (validate_path).
- `confirm_with_captain()` helper for destructive/expensive ops (60s timeout, default = deny).
- `data/tool_log.db` audit log (SQLite, append-only): timestamp, tool, inputs, result, exit_status, confirmation_status.

### 6 sub-tasks

1. **`WorkspaceBoundTool` base class** (45 min) — `aureon_agent/tools/{base,confirm,log}.py`. `validate_path()` rejects symlinks outside allowlist, errors are clear.
2. **`terminal` tool** (90 min) — `aureon_agent/tools/terminal.py`. Allowlist runs, destructive asks, no `shell=True`, 30s timeout, 50KB output cap.
3. **`file` tool** (90 min) — `aureon_agent/tools/file.py`. 3 sub-tools, workspace allowlist, binary rejected, UTF-8 only.
4. **`web` tool** (90 min) — `aureon_agent/tools/web.py`. DuckDuckGo HTML search + httpx fetch. Robots.txt respected. UA header.
5. **Registry integration** (45 min) — `agent_runtime.py` registers all 3, dispatches by name.
6. **Telemetry + doctor + docs** (45 min) — `aureon-agent tool-log --last 10` CLI, doctor checks workspace allowlist, `docs/tools.md` design doc.

### Acceptance criteria

- [ ] `validate_path` enforces `~/dev-shared/projects/` (rw) + `~/.openclaw/workspace/` (ro)
- [ ] `terminal` allowlisted commands run without confirmation
- [ ] `terminal` destructive commands always ask
- [ ] `terminal` rejects string commands (no shell injection)
- [ ] `file` rejects binary writes
- [ ] `web` search returns `{title, url, snippet}` list
- [ ] All 3 tools log to `data/tool_log.db`
- [ ] Live test via Telegram: `ls`, `read README.md`, `search "Ollama version"`
- [ ] `pytest tests/` passes (no regressions)
- [ ] `python tests/smoke.py` passes
- [ ] `aureon-agent-doctor` passes

### Out of scope (v1)

`browser` / `computer_use` desktop automation. `image_gen` / `video_gen` (separate services). `spotify` / `homeassistant` / `yuanbao` (services Captain doesn't use). Per-command timeout overrides. Background processes. Real-time streaming output. Per-channel tool policy (server/group restrictions). Tool usage analytics. Brave API (v2). Command history file.

---

## 2. Tier 2 tools (todo, clarify)

**Branch:** `feat/aureon-agent-tier2-tools` (off `dev`, after Tier 1)
**Complexity:** Small-Medium — 2 tools, but `clarify` requires ReAct pause/resume
**Estimated effort:** 1-2 evenings, ~400 LoC + tests

### What this is

2 small tools that pair with the plan-node hard block: the agent maintains its own plan and asks clarifying questions before doing destructive work. Closes the loop on "3+ step task → block → read todo.md → ask Captain for plan → resume".

### Decisions confirmed with user (2026-07-13)

**`todo` tool:**
- 3 sub-tools: `todo_read(path="tasks/todo.md")` → string, `todo_write(path, content, append=False)` → overwrites or appends, `todo_add(path, item)` → appends `- [ ] {item}\n`.
- Default path `tasks/todo.md`. Path validation: `~/dev-shared/projects/` only (no writing to `~/.openclaw/`). Markdown format. Last-write-wins (no file locking for v1).

**`clarify` tool:**
- Schema requires `question` (string), optional `options` (list, 2-5 multiple-choice), optional `timeout_sec` (default 300, max 1800).
- 1-clarify-per-iteration cap (prevent infinite loops in same turn).
- 3-clarify-per-session cap.
- Timeout returns empty string + WARN. Agent treats as "no answer" — either proceed cautiously or block.
- Channel router change: Telegram/Discord adapter checks `pending_clarifications` for the session_id before processing a new turn. User reply routes to the future, not the normal handler.

### 4 sub-tasks

1. **`todo` tool** (60 min) — `aureon_agent/tools/todo.py`. 3 sub-tools, workspace allowlist, Markdown format.
2. **`clarify` tool** (90 min) — `aureon_agent/tools/clarify.py` + `agent_runtime.py` pause/resume via `asyncio.Future` + per-session `pending_clarifications` registry in `channels/router.py`.
3. **Registry integration** (30 min) — register both, dispatch by name.
4. **Telemetry + doctor + docs** (30 min) — `aureon-agent clarify-log --last 10` CLI, doctor checks.

### Acceptance criteria

- [ ] `todo` 3 sub-tools work, workspace allowlist enforced
- [ ] `clarify` sends question via channel, waits for reply, returns answer
- [ ] `clarify` 1-per-iteration + 3-per-session caps enforced
- [ ] `clarify` timeout returns empty string + WARN log
- [ ] Channel router routes user replies to pending clarifications, not new turns
- [ ] Both tools log to `data/tool_log.db`
- [ ] Live test via Telegram: "show me the current plan" → `todo_read`, "add to plan" → `todo_add`, "build a thing" → `clarify` asks, Captain replies, agent continues

### Out of scope (v1)

Subagent `todo`. Rich `clarify` UIs (Telegram inline keyboards, Discord buttons). `clarify` with file attachments. `clarify` chain. Multi-party clarifications. Persistent clarification state across bot restarts. `todo` history / archive. `todo` schema validation.

---

## 3. Subagent dispatch via `delegate_task`

**Branch:** `feat/aureon-agent-subagent-dispatch` (off `dev`, after Tier 1)
**Complexity:** Non-trivial — tool integration + subprocess + sandbox + audit
**Estimated effort:** 2 evenings, ~500 LoC + tests

### What this is

Wire a `delegate_task` tool into the agent's registry. When the agent needs parallel work, long-running research, or code review, it spawns a subagent (claude-code CLI in v1) and gets the result back. This is the single feature that turns aureon-agent from "Telegram chatbot" into "AI operator".

### Decisions confirmed with user (2026-07-13)

- **Backend:** claude-code CLI (already on athena). OpenCode is the v2 second option. No new subagent runtime — shell out.
- **Result format:** subagent returns markdown (or stdout), pasted into parent context. Wait for full output, then resume.
- **Scope:** ONE concurrent subagent in v1 (FIFO queue). Multiple concurrent = v2.
- **Timeout:** 5 min hard. On timeout, kill subprocess, return "subagent timed out" to Captain, log failure.
- **Sandbox:** temp dir `/tmp/aureon-subagent-<uuid8>/` with source repo read-only bind-mounted. Files written by subagent inspected by parent before applying to real repo.
- **Cost control:** estimate token count before dispatch. If > 50K, require Captain confirmation.
- **Audit:** every dispatch logged to `data/subagent_log.db` (SQLite, append-only): timestamp, task description, subagent type, token count, exit status, result summary.
- **Bypass:** tool always available. Captain can disable via `AUREON_SUBAGENT_DISABLED=1` (tests, debugging).

### 6 sub-tasks

1. **Subagent backend abstraction** (60 min) — `subagent/{__init__,base,task,result,claude_code}.py`. `SubagentBackend` ABC with `dispatch()` method. `ClaudeCodeBackend` wraps `claude` CLI, parses JSON output, enforces timeout.
2. **Sandbox + audit logging** (60 min) — `subagent/sandbox.py` creates temp dir with read-only source. `data/subagent_log.db` schema: `dispatch_log(id, task_id, created_at, task_description, backend, token_count, exit_code, duration_sec, result_summary)`.
3. **`delegate_task` tool integration** (90 min) — synthesized tool, name+description+schema, execute function: build SubagentTask, create sandbox, write briefing.md, call backend, log, cleanup, return result dict. Cost control: estimate tokens before dispatch.
4. **Channel integration** (30 min) — when `delegate_task` returns, parent response mentions subagent + audit link. No streaming of subagent output (wait-for-completion).
5. **Captain-facing affordances** (30 min) — `aureon-agent subagent-log --last 10` CLI, doctor check.
6. **Tests + live verification** (60 min) — pytest, smoke, doctor, 2 live tests via Telegram.

### Acceptance criteria

- [ ] `delegate_task` tool in registry, accepts task_description + optional backend/model/timeout_sec/files_to_inspect
- [ ] `claude-code` backend dispatches via subprocess with timeout + cleanup
- [ ] Sandbox creates temp dir with read-only source, cleans up on success/failure
- [ ] Audit log captures every dispatch
- [ ] Cost control refuses to dispatch if estimated tokens > 50K
- [ ] Subagent result included in parent response
- [ ] `aureon-agent subagent-log --last 10` shows recent dispatches
- [ ] Live test: 2 different subagent tasks run end-to-end via Telegram

### Out of scope (v1)

Multiple concurrent subagents. Subagent-of-subagent. Cross-backend fallback. Cost dashboard. Persistent subagent sessions. Per-channel subagent policy. Streaming subagent output.

---

## 4. Plan-node hard block (v2)

**Branch:** `feat/aureon-agent-plan-node-hard-block` (off `dev`, after Tier 2)
**Complexity:** Small — soft warning already exists, promote to hard block + new heuristics
**Estimated effort:** 1 evening, ~200 LoC + tests

### What this is

Promote the existing soft-warning plan-node check to a hard block: when the agent receives a task that implies 3+ steps and the user hasn't written a plan, refuse to start work and ask Captain to write one first. Catches the "I'll just add this one thing" pattern before it cascades (lesson from 2026-06-16).

### Decisions confirmed with user (2026-07-13)

- **Threshold:** 3+ steps triggers the block. 1-2 steps proceed with just a soft warning.
- **Plan location:** `tasks/todo.md` (project) OR `~/.openclaw/workspace/tasks/todo.md` (Captain's master) — both count. Agent prefers project-level when scope is project-scoped.
- **Bypass:** magic phrases (`just do it`, `skip the plan`, `simple task`) — accepted, logged at WARN.
- **Subagent work:** doesn't trigger the block (subagents are already scoped by their kickoff).
- **Read-only operations:** don't trigger (e.g. "show me the doctor output" — 1 step).
- **Check happens in `agent_runtime.py` BEFORE the first ReAct iteration**, not at the channel layer.
- **Failure mode:** plan file unwritable → fail open, WARN log.

### 4 sub-tasks

1. **Step-counting heuristic** (60 min) — replace simple keyword regex with structured detector: count imperative verbs (`build, create, fix, add, remove, update, implement, deploy, test, write, refactor, migrate`), count conjunctions (`and, then, also, plus, after that, next`), count file paths, count URLs. 3+ = needs plan. Read-only keywords (`show, list, display, what is, how many`) bypass.
2. **Plan detection** (45 min) — read `tasks/todo.md` + `~/.openclaw/workspace/tasks/todo.md`, count `- [ ]` lines. ≥1 = plan exists. Bypass phrases match case-insensitive regex. Both files: prefer project-level.
3. **Hard block in `agent_runtime.py`** (45 min) — `plan_node.require_plan(user_message)` returns `(ok, reason)`. Called at top of `handle_message()`. If `ok=False`, return structured response: "🛑 Plan needed. This task has 3+ steps but `tasks/todo.md` has no `- [ ]` items. Add a plan or say 'just do it' to bypass."
4. **Telemetry + test coverage** (30 min) — counter `plan_node_blocks_total`, doctor check, CLAUDE.md hard constraints update, tests for 6 scenarios, live test.

### Acceptance criteria

- [ ] Agent blocks 3+ step tasks without a plan, with clear Telegram/Discord message
- [ ] Agent proceeds when plan exists
- [ ] Agent proceeds when bypass phrase used, with WARN log
- [ ] Read-only requests never trigger
- [ ] Step counter catches: 3+ imperative verbs, 3+ file paths, 3+ URLs
- [ ] Plan file read errors fail open
- [ ] Doctor passes
- [ ] pytest passes (8+ tests)
- [ ] Live test: 3-step task blocks, bypass phrase works, plan file works

### Out of scope (v1)

Plan quality checking (LLM-as-judge). Multi-file plan mode (`tasks/plan.md` separate). Plan-node config in `.env`. Bypass audit log file. Plan editor (Telegram message → write to `tasks/todo.md`).

---

## 5. Session compaction — already shipped ✅

**Status:** Merged in PR #16 at commit `d3cf3b2`. Branch `feat/aureon-agent-session-compaction` cleaned up.

### What was built

View-layer compaction: when `token_count(history) > compact_threshold`, summarize old turns and replace with a single summary message in the LLM's view. Recent turns stay verbatim. **`messages` SQLite table never modified** — full history stays for audit.

### Implementation recap

- `aureon_agent/models.py` — `MODEL_CONTEXT_WINDOWS` lookup (32K / 128K / 200K / 1M)
- `compaction/counter.py` — `tiktoken` `cl100k_base` + `len//4` fallback
- `compaction/threshold.py` — `compute_compact_threshold()` + `compute_recent_verbatim_size() = min(4000, threshold * 0.2)`
- `compaction/summarizer.py` — LLM summarizer, 300 max output tokens, 30s timeout, degraded fallback on failure
- `compaction/log.py` — `compaction_runs` table in `data/compaction_log.db` (append-only)
- `agent_runtime.py` — `_maybe_compact()` + `_compact()` wired into `run()`, gated by `AUREON_COMPACTION_ENABLED` (default off), fail open
- `aureon_agent/cli.py` — `compaction-log [--last|--session|--model]` subcommand
- `aureon_agent/doctor.py` — `check_compaction_log` + `check_model_known`
- 24 tests passing

### Deferred

Live-Telegram round-trip test (manual: send 30+ messages on a 32K model, watch for auto-compaction). Tracked in `tasks/todo.md`.

### Reference

- Original kickoff: see git history of `tasks/kickoff-session-compaction.md` (was 230 lines, now deleted in this cleanup)
- Implementation commit: `e7b99f3` on `dev`
- Live in production under systemd (PID 2372177 as of last check)

---

## Dispatch order

**Recommended:**

1. **Tier 1 tools** first — highest leverage, biggest PR. Adds 3 capabilities the agent is missing.
2. **Tier 2 tools** second — smaller, slots into the runtime alongside Tier 1's `WorkspaceBoundTool` base class.
3. **Subagent dispatch** third — biggest single feature, but needs the other tools in place to be useful end-to-end.
4. **Plan-node hard block** last — closes the loop. Without the tools, plan-node is a blocker with no escape hatch. With the tools (especially `clarify`), the agent can ask Captain for the plan in-line.

**Alternative order (if Captain prefers tools-first to use them, then add discipline later):**

1. Tier 1
2. Tier 2
3. Subagent
4. Plan-node

Both are valid. The recommended order is "capability first, then discipline" — agents that can do things, then learn to ask before doing dangerous things.

## Branch discipline (applies to all 5 PRs)

- One task per branch: `feat/aureon-agent-tier1-tools`, `feat/aureon-agent-tier2-tools`, etc.
- Branch off `dev`. PR against `dev`. Merge with `--merge` (no fast-forward).
- One commit per task, conventional `feat:` or `fix:` prefix.
- After merge, keep work branches on remote per standing rule. Don't auto-delete.

## Out of scope (all 5 work items combined)

- MCP integration (Phase 7, separate kickoff) — Notion, Gmail, GitHub
- Webhook mode for Telegram (replace polling)
- Server/group channel support
- Image/video generation (separate services)
- `nano-banana-pro` skill wiring (real image gen, separate work)
- Discord live test (code built, never tested)
- Per-channel tool policy (server/group = restricted)
- Subagent streaming output
- Subagent cost dashboard
- Cross-session compaction
- Hierarchical compaction (summarize summaries)

## Full spec references

- This file: `tasks/kickoff.md`
- Doctrine: `~/.openclaw/workspace/MEMORY.md` §Olympus + §Lessons
- Per-project AGENTS.md 6-rule contract
- 6-rule contract: see `AGENTS.md` (the project file)
- Completed work history: `tasks/DEVLOG.md`
- Current task tracking: `tasks/todo.md`
