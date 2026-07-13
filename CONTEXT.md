# CONTEXT.md — aureon-agent

> Single source of truth for stack, infrastructure, decisions, and conventions.
> Every agent reads this before touching any file.

---

## What this is

A personal AI agent for Vishal ("Captain"). Telegram + Discord channels. Doctrine-aware (loads SOUL/USER/IDENTITY/WORKFLOW/MEMORY from `~/.openclaw/workspace/`). Modeled on Tiny-OpenClaw's 8-component architecture, with Hermes-flavored deltas (Ollama local + cloud, SQLite, streaming, multi-channel, plan-node soft check, subagent dispatch via `delegate_task`).

## Mental model

This is a **local-first agent**, not a SaaS. It runs on athena (homelab), talks to you on Telegram or Discord, and routes complex work to coding sub-agents (claude-code, opencode, codex, abacus, agy, copilot — see `workspace/MEMORY.md` §Olympus). The agent itself is the orchestration layer; it does NOT do long-running coding work itself. It plans, delegates, and verifies.

## Stack

- **Language:** Python 3.12 (async-first, OpenClaw convention)
- **LLM:** Ollama via OpenAI-compat (`https://ollama.com/v1` for cloud, `http://127.0.0.1:11434/v1` for local)
- **Telegram:** `python-telegram-bot[rate-limiter]`
- **Discord:** `discord.py`
- **DB:** `aiosqlite` (WAL mode) — matches your `openclaw.sqlite` pattern
- **HTTP:** `httpx` (async) for Ollama + tool calls
- **File watching:** `watchfiles` for skill hot-reload
- **Config:** `.env` via `python-dotenv` (never committed)
- **HTTP health:** `aiohttp` (optional) on `127.0.0.1:7777/health` for systemd watchdog

## Where it runs

- **Host:** athena (Radxa Rock 5T, ARM64, 24GB)
- **Runtime:** `python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- **Tailscale sidecar pattern:** N/A (single Python process, not docker)
- **Process management:** systemd user service at `~/.config/systemd/user/aureon-agent.service` (post-MVP)
- **DB location:** `data/sessions.db`, `data/memory.db` (gitignored)
- **No `0.0.0.0` binds.** Localhost or Tailscale only.

## Architecture (8 components, ported from Tiny-OpenClaw)

1. **Channel Router** — multiplexes Telegram + Discord into unified message stream
2. **Channel adapters** — `channels/telegram.py`, `channels/discord.py`, ABC at `channels/base.py`
3. **Session Manager** — SQLite-backed per-chat history, key=`f"{channel}:{client_id}"`
4. **Memory** — SQLite-backed key-value, `note:*` namespace injected into system prompt
5. **Skill Loader** — scans `workspace/skills/`, parses OpenClaw SKILL.md frontmatter, hot-reloads
6. **Context Builder** — assembles SOUL + IDENTITY + skills + memory + time into <2K token system prompt
7. **Agent Runtime** — ReAct loop (MAX_TOOL_ROUNDS=5), Ollama streaming, plan-node soft check, caveman-aware
8. **main.py** — wires all 7, handles SIGTERM, optional health endpoint

Reference implementation: `references/tiny-openclaw/` (8 files, pinned commit `a4cb8cb94`).

## Channel policy (per `~/.openclaw/workspace/channel-policy-spec.md`)

| Channel context | Exec ask | Security | Elevated | Destructive | External |
|---|---|---|---|---|---|
| Telegram DM | `on-miss` | `allowlist` | `no` | confirm required | `no` default |
| Discord DM | `on-miss` | `allowlist` | `no` | confirm required | `no` default |
| Discord server | `always` | strict `allowlist` | `no` | confirm required | `no` default |
| Telegram group | `always` | `deny` | `no` | confirm required | `no` default |

**Initial rollout:** Telegram DM + Discord DM only. Server/group support in v2.

## Directory structure (target — 14 files across 5 phases)

```
aureon-agent/
├── main.py                       # entry (Phase 4)
├── agent_runtime.py              # ReAct loop (Phase 2)
├── context_builder.py            # multi-source system prompt (Phase 2)
├── memory.py                     # SQLite Memory (Phase 2)
├── session_manager.py            # SQLite SessionManager (Phase 2)
├── skill_loader.py               # OpenClaw SKILL.md format (Phase 2)
├── plan_node.py                  # soft-warning helper (Phase 4)
├── lessons.py                    # append to workspace/tasks/lessons.md (Phase 4)
├── channels/
│   ├── base.py                   # Channel ABC (Phase 3)
│   ├── router.py                 # ChannelRouter (Phase 3)
│   ├── telegram.py               # Telegram adapter (Phase 3)
│   └── discord.py                # Discord adapter (Phase 3)
├── workspace/                    # symlinks to ~/.openclaw/workspace/ (Phase 1)
├── data/                         # gitignored: sessions.db, memory.db (Phase 2+)
├── tests/
│   ├── smoke.py                  # smoke tests (Phase 5)
│   └── test_agent_loop.py        # agent loop test (Phase 5)
├── references/
│   └── tiny-openclaw/            # 8-file reference, pinned commit (Phase 1)
├── .github/workflows/ci.yml      # Python 3.12 CI (Phase 1)
├── CLAUDE.md                     # this file's sibling
├── AGENTS.md                     # 6-rule per-project contract
├── CONTEXT.md                    # this file
├── README.md                     # setup + run + workspace restore
├── requirements.txt              # deps
└── .gitignore                    # .env, *.db, __pycache__, workspace scratch dirs
```

## Conventions

- **Python style:** PEP 8, type hints on all public functions, async-first (`async def` for I/O).
- **No `print()` in production code** — use `logging` module (configured in main.py).
- **No raw `open()` for SQLite** — go through `Memory` and `SessionManager` classes only.
- **Tool results** must be JSON-serializable dicts, never raw exceptions.
- **Skill frontmatter:** `name` + `description` (matches OpenClaw SKILL.md format). Optional `metadata`, `user-invocable`, `homepage`.
- **Skill handler signature:** `async def execute(tool_name: str, tool_input: dict, context: dict) -> dict` — `context` always has `session_id`, `memory`, optional `channel` + `client_id`.
- **Channel reply size limits:** Telegram 4096 chars, Discord 2000 chars. Chunk on word boundaries.
- **Streaming throttle:** 1 edit/sec per chat (Telegram `editMessageText`, Discord `message.edit`).
- **Never log secrets.** Redact tokens in error messages.
- **Never commit `.env`, `data/*.db`, `__pycache__/`, `workspace/.openclaw/`, `workspace/.pi/`, `workspace/.venv-*/`.**

## Current focus

**Phase 2 (next):** SQLite Memory + SessionManager. Sub-task 3 from `tasks/kickoff-aureon-agent.md`. Then skill loader (4), context builder (5), agent runtime (6). After Phase 2 complete, agent can hold a conversation with no tools.

## Agents

| Agent | Role | Reads |
|---|---|---|
| Claude Code (athena tmux) | Local coding session. SQLite, file edits, channel testing. | `CLAUDE.md` + `CONTEXT.md` + `tasks/DEVLOG.md` |
| Claude Code (Anthropic cloud) | Cloud sibling. Skill load tests, lint, e2e audit. | Same as local (no secrets access) |
| Opencode | Fast inline edits, hotfixes. | `CONTEXT.md` + `tasks/DEVLOG.md` |
| Hermes | Plan/audit/scope gate. Triage PRs. | All of the above + `workspace/MEMORY.md` |

## Decision log

- **2026-07-13:** Project bootstrapped. Doctrine symlinked. SQLite chosen over JSON. Ollama + cloud fallback chosen over Anthropic hardcode. Telegram + Discord chosen over multi-platform (5 channels would dilute focus). Caveman mode already-on in `~/.hermes/config.yaml`.
- **2026-07-13:** Plan-node check is **soft warning** in v1 (not block). Full block in v2.
- **2026-07-13:** Subagent dispatch reuses Hermes `delegate_task` (no new subagent runtime).
- **2026-07-13:** All 8 shipped OpenClaw skills are prose-only SKILL.md (no `handler.py`) — not the Tiny-OpenClaw `tools`+`execute()` shape the kickoff spec assumed. `skill_loader.py` supports both: real `handler.py` skills load as executable tools; prose-only skills get one synthesized `read_skill_<name>` tool that returns the skill body on demand.
- **2026-07-13:** Default `OLLAMA_MODEL` is `minimax-m2.5:cloud`, not `minimax-m3` — the local Ollama endpoint (`http://127.0.0.1:11434/v1`, the default `OLLAMA_BASE_URL`) only proxies `minimax-m2.5:cloud` / `gemma4:31b-cloud`. `minimax-m3` only exists on the `ollama-cloud` provider (`https://ollama.com/v1`, needs `OLLAMA_API_KEY`).
- **2026-07-13:** Tiny-OpenClaw reference vendored (pinned commit `a4cb8cb94`) at `references/tiny-openclaw/`. Offline-first, no network needed.
- **2026-07-13:** GitHub repo public per Captain. Workflow symlink to `~/dev-shared/workflow/` added per audit (was missing). CLAUDE.md rewritten to match mature-project structure (~241 lines, up from 51). `main` + `dev` branch model per project-init skill.

## What's NOT in v1

- Sub-agent dispatch via `delegate_task` (planned v2)
- Voice call (TwiMLo) integration
- Image generation (use `nano-banana-pro` skill instead)
- Multi-modal inputs (text-only)
- Webhook mode for Telegram (polling only in v1)
- Server/group channel support
- Plan-node hard block (soft warning only in v1)
- Compaction of long sessions
- Memory write from LLM (only via `memory_work` skill, like Tiny-OpenClaw)
- systemd user service (post-MVP)

## Key file paths

| What | Path |
|---|---|
| Doctrine source | `~/.openclaw/workspace/` (symlinked into `workspace/`) |
| Workflow files | `~/dev-shared/workflow/` (symlinked into `workflow/`, gitignored) |
| Skills | `workspace/skills/` (symlinked to `~/.openclaw/workspace/skills/`) |
| Daily memory | `workspace/memory/` (symlinked to `~/.openclaw/workspace/memory/`) |
| Captain's todo | `workspace/tasks/todo.md` (own copy) |
| Captain's lessons | `workspace/tasks/lessons.md` (own copy) |
| Project todo | `tasks/todo.md` (this project only) |
| Project devlog | `tasks/DEVLOG.md` |
| Project lessons | `tasks/lessons.md` |
| Project kickoff | `tasks/kickoff-aureon-agent.md` |
| Reference | `references/tiny-openclaw/` |
| Sessions DB | `data/sessions.db` (gitignored) |
| Memory DB | `data/memory.db` (gitignored) |
| Env | `.env` (gitignored) |
