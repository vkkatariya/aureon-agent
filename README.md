# aureon-agent

Hermes-flavored autonomous AI agent modeled on Tiny-OpenClaw's 8-component architecture, wired to your existing OpenClaw doctrine so every session knows who you are, how you work, and which sub-agent to route to.

## What it is

- **Local-first** AI agent. Telegram + Discord channels. Ollama local + cloud fallback.
- **Doctrine-aware.** Loads SOUL/USER/IDENTITY/WORKFLOW/MEMORY from your existing OpenClaw workspace at startup.
- **ReAct loop** with tool use via skills (OpenClaw SKILL.md format).
- **SQLite-backed** sessions + memory (no JSON files).
- **Streaming replies** to chat platforms (Telegram via `editMessageText`, Discord via `message.edit`).

## Architecture (Tiny-OpenClaw ports with Hermes-flavored deltas)

```
User (Telegram / Discord)
   ↓
[Channel Router]
   ├→ [Telegram Adapter]   ← python-telegram-bot, chat ID allowlist
   └→ [Discord Adapter]    ← discord.py, DM-only initially
   ↓
[Session Manager]  ← SQLite (data/sessions.db), key=channel:client_id
   ↓
[Agent Runtime]    ← ReAct loop, MAX_TOOL_ROUNDS=5, streaming
   ├→ [Context Builder]  ← SOUL + IDENTITY + skills + note:* + time
   ├→ [Plan Node]       ← soft warning if 3+ step task without todo.md
   └→ Ollama (OpenAI-compat: https://ollama.com/v1 or http://127.0.0.1:11434/v1)
   ↓ (if tool_use)
[Skill Loader]  ← scans workspace/skills/, parses SKILL.md frontmatter
   ↓
[Skill handlers]  ← 8 OpenClaw skills (caveman, homelab-*, project-init, ...)
   ↓
[Memory]  ← SQLite (data/memory.db), note:* namespace injected into prompt
   ↓ back up the chain
```

## Setup & First Install

```bash
git clone git@github.com:vkkatariya/aureon-agent.git
cd aureon-agent
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
aureon-agent postinstall
aureon-agent setup
```

## Commands

- **Start:** `aureon-agent start` or simply `aureon-agent`
- **Reconfigure:** `aureon-agent setup --section channel`
- **Reset:** `aureon-agent setup --reset`
- **Non-interactive:** `aureon-agent setup --non-interactive --telegram-bot-token "$TG" --telegram-allowed-chats 723865496`
- **Check health:** `aureon-agent doctor`
- **Stop daemon:** `aureon-agent stop`
- **Tail logs:** `aureon-agent logs`

## Setup Script Behavior

The `aureon-agent setup` wizard supports multiple modes:
- **Interactive (default):** Prompts for each value, offering to keep, modify, or reset existing configs.
- **Quick (`--quick`):** Skips sections that already have a valid configuration, only prompting for missing values.
- **Non-interactive (`--non-interactive`):** Bypasses all TUI prompts. Reuses existing config or relies entirely on command-line flags (e.g., `--telegram-bot-token`) and environment variables.
- **Reset (`--reset`):** Destroys the current configuration and starts fresh. Destructive action requires confirmation.

## Workspace

The `workspace/` directory contains symlinks to your existing OpenClaw doctrine (`~/.openclaw/workspace/`). One source of truth — edit there, not here.

If symlinks break (e.g., fresh clone on a new machine):

```bash
cd workspace
for f in SOUL.md USER.md IDENTITY.md WORKFLOW.md MENTAL-MODEL-TEMPLATE.md MEMORY.md HEARTBEAT.md channel-policy-spec.md handoff-template.md; do
  ln -sf ~/.openclaw/workspace/$f $f
done
ln -sf ~/.openclaw/workspace/skills skills
ln -sf ~/.openclaw/workspace/memory memory
```

## Tests

```bash
python tests/smoke.py
python tests/test_agent_loop.py
```

## License

Personal project. Not for redistribution.
