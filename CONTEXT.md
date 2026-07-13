# CONTEXT.md — aureon-agent

> Single source of truth for stack, infrastructure, decisions, and conventions.
> Every agent reads this before touching any file.

---

## What this is

A personal AI agent for Vishal ("Captain"). Telegram + Discord channels. Doctrine-aware (loads SOUL/USER/IDENTITY/WORKFLOW from `~/.openclaw/workspace/`). Modeled on Tiny-OpenClaw's 8-component architecture, with Hermes-flavored deltas (Ollama local + cloud, SQLite, streaming, multi-channel, plan-node soft check, subagent dispatch via `delegate_task`).

## Mental model

This is a **local-first agent**, not a SaaS. It runs on athena (homelab), talks to you on Telegram or Discord, and routes complex work to coding sub-agents (claude-code, opencode, codex, abacus, agy, copilot — see `~/.openclaw/workspace/MEMORY.md` §Olympus). The agent itself is the orchestration layer; it does NOT do long-running coding work itself. It plans, delegates, and verifies.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | OpenClaw convention, async-first |
| LLM | Ollama (OpenAI-compat) | Local + cloud per existing `~/.openclaw/openclaw.json` |
| Telegram | `python-telegram-bot[rate-limiter]` | Most mature async lib |
| Discord | `discord.py` | De facto standard |
| DB | `aiosqlite` (WAL mode) | Matches your `openclaw.sqlite` pattern |
| HTTP | `httpx` (async) | For Ollama + tool calls |
| File watching | `watchfiles` | For skill hot-reload |
| Config | `.env` via `python-dotenv` | Standard, never committed |

## Architecture (8 components, ported from Tiny-OpenClaw)

1. **Channel Router** — multiplexes Telegram + Discord into unified message stream
2. **Channel adapters** — `channels/telegram.py`, `channels/discord.py`, ABC at `channels/base.py`
3. **Session Manager** — SQLite-backed per-chat history, key=`f"{channel}:{client_id}"`
4. **Memory** — SQLite-backed key-value, `note:*` namespace injected into system prompt
5. **Skill Loader** — scans `workspace/skills/`, parses OpenClaw SKILL.md frontmatter, hot-reloads
6. **Context Builder** — assembles SOUL + IDENTITY + skills + memory + time into <2K token system prompt
7. **Agent Runtime** — ReAct loop (MAX_TOOL_ROUNDS=5), Ollama streaming, plan-node soft check, caveman-aware
8. **main.py** — wires all 7, handles SIGTERM, optional health endpoint

## Channel policy (per `~/.openclaw/workspace/channel-policy-spec.md`)

| Channel context | Exec ask | Security | Elevated | Destructive | External |
|---|---|---|---|---|---|
| Telegram DM | `on-miss` | `allowlist` | `no` | confirm required | `no` default |
| Discord DM | `on-miss` | `allowlist` | `no` | confirm required | `no` default |
| Discord server | `always` | strict `allowlist` | `no` | confirm required | `no` default |
| Telegram group | `always` | `deny` | `no` | confirm required | `no` default |

**Initial rollout:** Telegram DM + Discord DM only. Server/group support in v2.

## Infrastructure

- **Host:** athena (Radxa Rock 5T, ARM64, 24GB)
- **Runtime:** `python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- **Tailscale sidecar pattern:** N/A (this is a single Python process, not docker)
- **Process management:** systemd user service at `~/.config/systemd/user/aureon-agent.service` (TBD, not in v1)
- **Health check:** optional `aiohttp` server on `127.0.0.1:7777/health` (TBD)
- **DB location:** `data/sessions.db`, `data/memory.db` (gitignored)

## Hard rules (per OpenClaw MEMORY.md lessons)

- **No `0.0.0.0` binds.** Localhost or Tailscale only.
- **No force-push / destructive ops without explicit confirmation.** Captain says "go" before.
- **Telegram chat ID allowlist.** Drop messages from non-allowed chats silently.
- **Caveman mode always-on** in replies (per `agent.environment_hint` + SOUL.md `caveman-begin/end` block).
- **Scope discipline:** write what was asked, stop, don't add scope. (Lesson from 2026-06-16/17.)
- **OpenClaw config (`~/.openclaw/openclaw.json`) is locked.** Read-only inspection OK, any write → ask first.

## Decision log

- **2026-07-13:** Project bootstrapped. Doctrine symlinked. SQLite chosen over JSON. Ollama + cloud fallback chosen over Anthropic hardcode. Telegram + Discord chosen over multi-platform (5 channels would dilute focus). Caveman mode already-on in `~/.hermes/config.yaml`.
- **2026-07-13:** Plan-node check is **soft warning** in v1 (not block). Full block in v2.
- **2026-07-13:** Subagent dispatch reuses Hermes `delegate_task` (no new subagent runtime).
- **2026-07-13:** All 8 shipped OpenClaw skills are prose-only SKILL.md (no `handler.py`) — not the Tiny-OpenClaw `tools`+`execute()` shape the kickoff spec assumed. `skill_loader.py` supports both: real `handler.py` skills load as executable tools; prose-only skills get one synthesized `read_skill_<name>` tool that returns the skill body on demand.
- **2026-07-13:** Default `OLLAMA_MODEL` is `minimax-m2.5:cloud`, not `minimax-m3` — the local Ollama endpoint (`http://127.0.0.1:11434/v1`, the default `OLLAMA_BASE_URL`) only proxies `minimax-m2.5:cloud` / `gemma4:31b-cloud`. `minimax-m3` only exists on the `ollama-cloud` provider (`https://ollama.com/v1`, needs `OLLAMA_API_KEY`).

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

## Key file paths

| What | Path |
|---|---|
| Doctrine source | `~/.openclaw/workspace/` (symlinked into `workspace/`) |
| Skills | `workspace/skills/` (symlinked to `~/.openclaw/workspace/skills/`) |
| Daily memory | `workspace/memory/` (symlinked to `~/.openclaw/workspace/memory/`) |
| Captain's todo | `workspace/tasks/todo.md` (own copy) |
| Captain's lessons | `workspace/tasks/lessons.md` (own copy) |
| Project todo | `tasks/todo.md` (this project only) |
| Project devlog | `tasks/DEVLOG.md` |
| Sessions DB | `data/sessions.db` (gitignored) |
| Memory DB | `data/memory.db` (gitignored) |
| Env | `.env` (gitignored) |
| Kickoff spec | `tasks/kickoff-aureon-agent.md` |
