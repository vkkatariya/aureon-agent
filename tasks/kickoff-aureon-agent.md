# Task: Build `aureon-agent` from scratch (Hermes-flavored OpenClaw clone)

**Branch:** `feat/aureon-agent-bootstrap` (off `main`)
**Mode:** Builder
**Complexity:** Non-trivial — full design + 14 file scaffold + workspace wiring
**Estimated effort:** 2–3 evenings, ~700 LoC

---

## Setup

- **Project:** `aureon-agent`
- **Path on athena:** `~/dev-shared/projects/aureon-agent/`
- **Working directory:** this repo
- **Active branch:** `feat/aureon-agent-bootstrap` (off `main`)
- **Session name:** `[aureon-agent]-local` (you're the local session, persistent tmux)
- **No cloud session needed** — this is screen + print design work, no `npm install` / Playwright-heavy operations

## What this is

A from-scratch, Hermes-flavored AI agent modeled on Tiny-OpenClaw's 8-component architecture, but wired to your existing OpenClaw doctrine (SOUL/USER/IDENTITY/WORKFLOW/MEMORY) so every new session knows who you are, how you work, and which sub-agent to route to.

**Key differences from Tiny-OpenClaw:**

| Tiny-OpenClaw | aureon-agent |
|---|---|
| Hardcoded Anthropic Messages API | Ollama local + cloud fallback (per `~/.openclaw/openclaw.json`) |
| Telegram only | Telegram + Discord (channel ABC + adapters) |
| JSON files for sessions/memory | SQLite (matches `openclaw.sqlite` pattern) |
| No streaming | Stream tokens to Telegram via `editMessageText` |
| Skills hardcoded in code | Loaded from `skills/` folder, OpenClaw SKILL.md format |
| No doctrine loading | Loads SOUL/USER/IDENTITY/WORKFLOW/MEMORY at startup |
| No plan-node check | Reads `tasks/todo.md` per session, blocks 3+ step tasks without plan |
| No subagent dispatch | Integrates Hermes `delegate_task` for parallel work |
| English only | Matches user language (caveman rule: compress style, not language) |
| One-shot 5-round ReAct | Same — keep it simple |

## Decisions confirmed with user (2026-07-13)

- **Name:** `aureon-agent` (matches your IDENTITY.md "Aureon" name)
- **Doctrine source:** symlink to `~/.openclaw/workspace/` files (one source of truth, no drift)
- **LLM:** Ollama local + cloud fallback, configured per existing `~/.openclaw/openclaw.json`
- **Channels:** Telegram (primary) + Discord (secondary), with channel-policy per `channel-policy-spec.md`
- **Storage:** SQLite for sessions + memory (no JSON files)
- **Streaming:** yes, with Telegram `editMessageText` throttled to 1 edit/sec
- **Skills:** OpenClaw SKILL.md format (`name` + `description` frontmatter + `handler.py` with `tools` list + async `execute`)
- **No plan-node blocking initially** — soft warning when 3+ step task started without todo.md plan; full block in v2
- **Subagent dispatch:** reuse Hermes `delegate_task` (already in your stack) for parallel work

## Source files to reference (do NOT create from scratch)

- **`~/.openclaw/workspace/SOUL.md`** — agent identity + caveman always-on rules
- **`~/.openclaw/workspace/USER.md`** — Captain = Vishal, TZ Europe/Berlin
- **`~/.openclaw/workspace/IDENTITY.md`** — Aureon 🦾, 4 modes
- **`~/.openclaw/workspace/WORKFLOW.md`** — 6-rule execution protocol
- **`~/.openclaw/workspace/MENTAL-MODEL-TEMPLATE.md`** — mode selection
- **`~/.openclaw/workspace/MEMORY.md`** — Olympus orchestration + agent roster + lessons
- **`~/.openclaw/workspace/channel-policy-spec.md`** — per-channel exec policy
- **`~/.openclaw/workspace/skills/`** — 8 existing skills (caveman, homelab-*, project-init, etc.)
- **OpenClaw memory/`** — daily notes pattern
- **Tiny-OpenClaw repo:** `https://github.com/ashishbamania/Tiny-OpenClaw` — 8-file reference architecture

## Read these on session start (in order)

1. `~/dev-shared/projects/aureon-agent/CLAUDE.md` — project context (write first)
2. `~/dev-shared/projects/aureon-agent/CONTEXT.md` — stack, infra, design tokens (write first)
3. `tasks/kickoff-aureon-agent.md` (this file) — the spec
4. `~/.openclaw/workspace/SOUL.md` — agent identity
5. `~/.openclaw/workspace/USER.md` — user preferences
6. `~/.openclaw/workspace/IDENTITY.md` — operating modes
7. `~/.openclaw/workspace/WORKFLOW.md` — execution protocol
8. `~/.openclaw/workspace/MENTAL-MODEL-TEMPLATE.md` — mode selection
9. `~/.openclaw/workspace/MEMORY.md` — long-term curated state
10. `~/.openclaw/workspace/memory/2026-07-1?.md` — latest daily notes
11. `~/.openclaw/workspace/tasks/todo.md` — current work
12. `~/.openclaw/workspace/tasks/lessons.md` — prevention rules

## Your role

You are building a Python project. Single repo. Per-project AGENTS.md contract applies:
1. Plan node (todo.md before 3+ step code)
2. Subagent strategy (parallel work → delegate_task)
3. Self-improvement loop (lessons.md on correction)
4. Verification before done
5. Demand elegance (balanced)
6. Autonomous bug fixing

---

## 14 deliverables (in order)

### Phase 1: Workspace + doctrine (foundation)

**Sub-task 1: Workspace symlinks (10 min)**
- Create `workspace/` dir in project root
- Symlink all OpenClaw doctrine files: `SOUL.md`, `USER.md`, `IDENTITY.md`, `WORKFLOW.md`, `MENTAL-MODEL-TEMPLATE.md`, `MEMORY.md`, `HEARTBEAT.md`, `channel-policy-spec.md`, `handoff-template.md` → `~/.openclaw/workspace/<same>.md`
- Symlink `workspace/skills/` → `~/.openclaw/workspace/skills/`
- Symlink `workspace/memory/` → `~/.openclaw/workspace/memory/`
- Create `workspace/tasks/todo.md` + `workspace/tasks/lessons.md` (own copies, not symlinks — these get written to)
- Verify: `readlink workspace/SOUL.md` returns the openclaw path

**Sub-task 2: Project bootstrap files (15 min)**
- `CLAUDE.md` — Claude Code session context, references this kickoff + the symlinked doctrine
- `CONTEXT.md` — stack (Python 3.12, httpx, aiosqlite, python-telegram-bot, discord.py), infra (athena homelab, port 0.0.0.0:X for Telegram webhook, 127.0.0.1 only for local), design tokens (caveman always-on, structured output)
- `AGENTS.md` — 6-rule per-project contract (copy from your OpenClaw MEMORY.md §"Per-Project AGENTS.md Contract")
- `README.md` — what this is, how to run, symlink gotchas
- `.gitignore` — `.env`, `__pycache__/`, `data/*.db`, `data/*.db-wal`, `data/*.db-shm`, `workspace/.openclaw/`, `workspace/.pi/`, `workspace/.venv-*/`
- `requirements.txt` — `httpx`, `python-telegram-bot[rate-limiter]`, `discord.py`, `aiosqlite`, `python-dotenv`

### Phase 2: Core runtime (Tiny-OpenClaw ports)

**Sub-task 3: Memory + Session (SQLite) (45 min)**
- `memory.py` — `Memory` class. Two stores:
  - `notes` table: `key TEXT PRIMARY KEY, value TEXT, updated_at REAL` (the `note:*` namespace)
  - `meta` table: `key TEXT PRIMARY KEY, value TEXT` (everything else, not injected into system prompt)
- `session_manager.py` — `SessionManager` class. `sessions` table: `session_id TEXT PRIMARY KEY, channel TEXT, client_id TEXT, created_at REAL, updated_at REAL`. `messages` table: `session_id TEXT, role TEXT, content TEXT, timestamp REAL, tool_calls TEXT, idx INTEGER`. Composite PK on (session_id, idx). 1-line invariant: every session row has matching messages, no orphans.
- Both files async (`aiosqlite`).
- Replace Tiny-OpenClaw's `MEMORY.json` / `SESSIONS.json` with `data/memory.db` / `data/sessions.db`.
- Concurrency: WAL mode, `asyncio.Lock` per session_id for write serialization.

**Sub-task 4: Skill loader (OpenClaw format) (30 min)**
- `skill_loader.py` — port Tiny-OpenClaw's loader, but parse OpenClaw `SKILL.md` frontmatter (may include `metadata`, `user-invocable`, `homepage`)
- Each skill: `name`, `description`, `tools` (list of dicts with `name`, `description`, `parameters`), `execute` (async callable)
- `context` passed to `execute`: `session_id`, `memory`, optional `channel` + `client_id`
- Add skill hot-reload: `watchfiles` (already in your stack) — when SKILL.md or handler.py changes, reload
- Verify all 8 OpenClaw skills load cleanly

**Sub-task 5: Context builder (doctrine-aware) (45 min)**
- `context_builder.py` — replace Tiny-OpenClaw's `build_system_prompt` with a multi-source assembler:
  1. SOUL.md (full content)
  2. IDENTITY.md (full content) — note the `caveman-begin/end` block in SOUL.md is auto-active
  3. Skill names + descriptions (only for active skills, OpenClaw convention)
  4. MEMORY.md `note:*` entries (filtered via Memory store, NOT full MEMORY.md — security boundary from OpenClaw AGENTS.md)
  5. Current time (UTC ISO)
- Build as a list of sections, join with `\n\n---\n\n` for readability
- Total target: <2K tokens (compact doctrine excerpts, not full files)

**Sub-task 6: Agent runtime (Ollama + streaming + plan-node soft check) (60 min)**
- `agent_runtime.py` — port Tiny-OpenClaw's `AgentRuntime` with these deltas:
  - **LLM:** Ollama via OpenAI-compat (`https://ollama.com/v1` for cloud, `http://127.0.0.1:11434/v1` for local). Reuse config from `~/.openclaw/openclaw.json` model routing.
  - **Streaming:** `async for chunk in client.stream(...)`, accumulate tokens, call `on_token` callback per chunk. Telegram channel throttles to 1 edit/sec.
  - **Plan-node soft check:** before each `run()`, peek at `workspace/tasks/todo.md`. If empty AND user message implies 3+ step task (heuristic: contains "build", "create", "fix", "add", "implement", OR >50 words), log warning `"⚠️ plan_node_miss: no todo.md plan for 3+ step task"`. Don't block — just warn. v2 will block.
  - **MAX_TOOL_ROUNDS = 5** (same as Tiny-OpenClaw)
  - **Caveman in replies:** when `on_token` callback receives the final text, ensure response follows caveman full rules. Don't apply to intermediate tool-result narration.
  - **Auto-clarity:** if user message matches destructive pattern (`rm -rf`, `drop table`, `force push`, `git push --force-with-lease`, `truncate`, `mkfs`), drop caveman for that response — emit a normal-prose safety warning.

### Phase 3: Channel adapters (multi-channel)

**Sub-task 7: Channel ABC (15 min)**
- `channels/base.py` — abstract `Channel` class:
  - `async def start()` — begin listening
  - `async def send_message(chat_id, text)` — send full text
  - `async def edit_message(chat_id, message_id, text)` — update sent message (for streaming)
  - `async def send_action(chat_id, action)` — "typing..." indicator
  - `async def stop()` — graceful shutdown
- `channels/router.py` — multiplexes incoming messages from multiple channels, dispatches to agent runtime, routes replies back to source channel

**Sub-task 8: Telegram adapter (45 min)**
- `channels/telegram.py` — port Tiny-OpenClaw's `telegram_channel.py` with these deltas:
  - Per channel-policy-spec.md: Telegram DM = Balanced profile (exec ask `on-miss`, security `allowlist`, no elevated)
  - Chat ID allowlist: env `TELEGRAM_ALLOWED_CHATS` (comma-separated). Drop all messages from other chats silently.
  - Streaming: send initial "..." message, then `editMessageText` with accumulating text, throttled to 1 edit/sec (use `asyncio.Lock` per chat)
  - Reply chunking: 4096 char limit (Telegram API), chunk on word boundaries
  - `on_token` callback wired to `edit_message`
  - `on_tool_use` callback → `send_action("typing")`

**Sub-task 9: Discord adapter (45 min)**
- `channels/discord.py` — `discord.py` library, similar to Telegram but:
  - Channel-policy: Discord DM = Balanced, Discord server = Strict
  - Discord message limit: 2000 chars
  - Streaming: edit message via `message.edit()` throttled
  - Bot invite link: `https://discord.com/oauth2/authorize?client_id=<DISCORD_APP_ID>&scope=bot&permissions=274877958144` (Send Messages + Read Message History + Manage Messages for edits)
  - DMs only initially; server support in v2

### Phase 4: Entry + integration

**Sub-task 10: main.py (30 min)**
- `main.py` — port Tiny-OpenClaw's main, but:
  - Load env: `TELEGRAM_BOT_TOKEN`, `DISCORD_BOT_TOKEN` (optional), `OLLAMA_BASE_URL` (default `http://127.0.0.1:11434/v1`), `OLLAMA_API_KEY` (optional), `OLLAMA_MODEL` (default `minimax-m3`), `TELEGRAM_ALLOWED_CHATS`
  - Wire: Memory + SessionManager + SkillLoader + AgentRuntime + ChannelRouter
  - Graceful shutdown: SIGTERM/SIGINT → close DB, close channels
  - Health check endpoint: optional `aiohttp` server on `127.0.0.1:7777/health` for systemd watchdog
  - `if __name__ == "__main__": asyncio.run(main())`

**Sub-task 11: Plan-node module (15 min)**
- `plan_node.py` — soft-warning helper extracted from Sub-task 6:
  - `def needs_plan(user_message: str) -> bool` — heuristic for 3+ step task
  - `async def check_plan(workspace_dir: str, user_message: str) -> str | None` — returns warning string or None
  - Called by `agent_runtime.run()` before the LLM call

**Sub-task 12: Lessons writer (15 min)**
- `lessons.py` — `append_lesson(workspace_dir, context, what_went_wrong, root_cause, prevention_rule)`:
  - Format from `~/.openclaw/workspace/tasks/lessons.md` template
  - Async file write with `asyncio.Lock` to prevent concurrent corruption
  - Triggers: manual via `/lesson` slash command in chat, or auto when user says "remember this" / "add to lessons" / explicit `/lesson <text>`

### Phase 5: Verification

**Sub-task 13: Smoke test (30 min)**
- `tests/smoke.py` — basic health checks:
  - All 8 OpenClaw skills load without error
  - Memory set/get roundtrip
  - Session create/add message/get history roundtrip
  - Context builder produces <2K token output
  - Ollama call returns non-empty response (mock if Ollama not running)
- `tests/test_agent_loop.py` — end-to-end: user message "what time is it?" → agent uses `datetime` skill → returns formatted time

**Sub-task 14: Dev workflow docs (20 min)**
- `README.md` — how to run (`python main.py`), env vars, channel allowlist setup, symlink restoration
- `tasks/DEVLOG.md` — initialize with this bootstrap session entry
- Commit + push branch
- Update root `~/dev-shared/notes/` with link to new project

---

## File layout (final)

```
~/dev-shared/projects/aureon-agent/
├── main.py                       # entry, env load, wire all components
├── agent_runtime.py              # ReAct loop, Ollama streaming, plan-node soft check
├── context_builder.py            # multi-source system prompt
├── memory.py                     # SQLite Memory (note:* + meta)
├── session_manager.py            # SQLite SessionManager
├── skill_loader.py               # OpenClaw SKILL.md format + hot-reload
├── plan_node.py                  # soft-warning helper
├── lessons.py                    # append to workspace/tasks/lessons.md
├── channels/
│   ├── __init__.py
│   ├── base.py                   # Channel ABC
│   ├── router.py                 # ChannelRouter
│   ├── telegram.py               # Telegram adapter
│   └── discord.py                # Discord adapter
├── workspace/                    # symlinks to ~/.openclaw/workspace/
│   ├── SOUL.md → ~/.openclaw/workspace/SOUL.md
│   ├── USER.md → ~/.openclaw/workspace/USER.md
│   ├── IDENTITY.md → ~/.openclaw/workspace/IDENTITY.md
│   ├── WORKFLOW.md → ~/.openclaw/workspace/WORKFLOW.md
│   ├── MENTAL-MODEL-TEMPLATE.md → ~/.openclaw/workspace/MENTAL-MODEL-TEMPLATE.md
│   ├── MEMORY.md → ~/.openclaw/workspace/MEMORY.md
│   ├── HEARTBEAT.md → ~/.openclaw/workspace/HEARTBEAT.md
│   ├── channel-policy-spec.md → ~/.openclaw/workspace/channel-policy-spec.md
│   ├── handoff-template.md → ~/.openclaw/workspace/handoff-template.md
│   ├── skills/ → ~/.openclaw/workspace/skills/
│   ├── memory/ → ~/.openclaw/workspace/memory/
│   └── tasks/
│       ├── todo.md               # own copy
│       └── lessons.md            # own copy
├── data/                         # gitignored
│   ├── sessions.db
│   └── memory.db
├── tests/
│   ├── smoke.py
│   └── test_agent_loop.py
├── .gitignore
├── requirements.txt
├── CLAUDE.md                     # Claude Code context
├── CONTEXT.md                    # stack, infra, design tokens
├── AGENTS.md                     # 6-rule per-project contract
├── README.md
└── tasks/
    ├── kickoff-aureon-agent.md   # this file
    └── DEVLOG.md                 # session log
```

## Truthfulness guardrails (per OpenClaw SOUL.md)

- Ground every claim in resume or verified sources
- Disallow defensive or apologetic language unless a real mistake was made
- Apply "scope discipline" lesson from `~/.openclaw/workspace/MEMORY.md` §"🦾 Lessons from 2026-06-16/17": write what was asked, stop, don't add scope

## Quality gates

- All 8 OpenClaw skills load cleanly
- Telegram DM allowlist enforced
- Streaming throttle ≤1 edit/sec per chat
- Context builder output <2K tokens
- DB writes serialized with `asyncio.Lock` per session_id
- No `0.0.0.0` binds (per homelab rules)
- No force-push / destructive ops without confirmation
- `agent.environment_hint` in `~/.hermes/config.yaml` already has caveman always-on — don't duplicate

## Definition of Done

- [ ] All 14 sub-tasks complete
- [ ] `python main.py` boots clean, connects to Ollama (or fails gracefully if Ollama down)
- [ ] Telegram bot responds to test message from allowed chat
- [ ] Discord bot responds to test DM
- [ ] `tests/smoke.py` + `tests/test_agent_loop.py` pass
- [ ] Workspace symlinks resolve correctly (verify with `readlink`)
- [ ] Caveman mode active in all replies (sample 3 messages, confirm terse style)
- [ ] Plan-node soft warning fires on 3+ step task without todo.md plan
- [ ] Lessons append works via `/lesson` slash command
- [ ] Branch committed + pushed, PR opened to `main`
- [ ] DEVLOG entry written

## Mode + Complexity

- **Mode:** Builder (system architecture + implementation)
- **Complexity:** Non-trivial full workflow (per MENTAL-MODEL-TEMPLATE.md §2)

## Branch strategy (per OpenClaw git contract)

- `main` — production, never edit directly
- `feat/aureon-agent-bootstrap` — this work, branched off `main`
- PR from `feat/*` → `main` after each phase completes
- Commit prefix: `feat(aureon-agent):` or `fix(aureon-agent):` or `docs(aureon-agent):`
- Push before session ends

## On completion

- Notify Captain via Telegram
- Append DEVLOG entry
- Wait for sign-off before merging to `main`
