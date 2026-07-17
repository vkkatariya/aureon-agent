<p align="center">
  <img src="assets/banner.svg" alt="aureon-agent — personal AI agent" width="100%">
</p>

<p align="center">
  <strong>aureon-agent 🦾</strong> — your personal AI operator.
</p>

<p align="center">
  <a href="https://github.com/vkkatariya/aureon-agent/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/vkkatariya/aureon-agent/ci.yml?style=for-the-badge" alt="CI status"></a>
  <a href="https://github.com/vkkatariya/aureon-agent/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="MIT License"></a>
  <a href="https://github.com/vkkatariya/aureon-agent"><img src="https://img.shields.io/badge/GitHub-vkkatariya%2Faureon--agent-181717?style=for-the-badge&logo=github" alt="GitHub"></a>
</p>

A **doctrine-aware** personal AI agent for [Vishal "Captain" Katariya](https://vishal-katariya.com). Runs on **athena** (Radxa Rock 5T, Tailscale-only), talks to you on **Telegram**, routes complex work to coding sub-agents (claude-code, opencode, codex, agy, copilot), and reaches external services through **MCP servers** (Notion, GitHub, Gmail). 8-component architecture inspired by the Tiny-OpenClaw reference (vendored at `references/tiny-openclaw/`).

| | |
|---|---|
| **LLM** | Ollama local (`http://127.0.0.1:11434/v1`) + cloud fallback (`https://ollama.com/v1`) |
| **Channels** | Telegram (primary, polling), Discord (optional, DM-only v1) |
| **Storage** | SQLite (sessions + memory + 3 append-only audit logs) |
| **Skills** | `SKILL.md` format (8 doctrine skills auto-loaded) |
| **Tools** | Hybrid: 8 doctrine skills + 5 inline tools + MCP servers (Notion/GitHub/Gmail) |
| **Agent loop** | ReAct, MAX_TOOL_ROUNDS=5, streaming, plan-node hard block |
| **Context** | Layered: brain layer (SOUL+IDENTITY+WORKFLOW+MEMORY+USER) always-on, skills/todo JIT |
| **Cron** | Background asyncio scheduler — isolated agent turns on a schedule, delivered to Telegram |
| **Style** | Caveman `full` mode always-on in replies |
| **Runtime** | Single Python process, `127.0.0.1` binds only, systemd user service |
| **License** | MIT |

```bash
# first install
git clone https://github.com/vkkatariya/aureon-agent.git ~/dev-shared/projects/aureon-agent
cd ~/dev-shared/projects/aureon-agent
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .
aureon-agent postinstall
aureon-agent setup       # interactive wizard
aureon-agent start       # or `aureon-agent` (default)
```

```bash
# reconfigure one section
aureon-agent setup --section channel
aureon-agent setup --reset
aureon-agent setup --non-interactive --telegram-bot-token "$TG" --telegram-allowed-chats 723865496
```

```bash
# health check + ops
aureon-agent doctor      # full health probe (skills, DB, env, Telegram, Ollama, systemd, MCP, cron)
aureon-agent status      # systemd status
aureon-agent logs        # journalctl -f
aureon-agent mcp list    # show configured MCP servers + their tools
aureon-agent stop        # stop the service
```

## What it does

- **Talks to you on Telegram.** Streams responses via `editMessageText`, throttled to 1 edit/sec per chat. Per-chat history in SQLite. Falls back to streamed text when the LLM returns an empty final response (no more silent "(no response)").
- **Loads doctrine every turn.** The "brain layer" (SOUL, IDENTITY, WORKFLOW, MEMORY, USER) is injected into the system prompt on every agent run — the agent's identity + your preferences are always present. Operational files (skills, todo, devlog) load just-in-time, bounded by a token budget.
- **Has 18 tools across 3 backends.** 8 doctrine skills (prose, auto-loaded), 5 inline tools (terminal, file, web, todo, clarify), `delegate_task` (subagent spawn), plus 5 MCP tools from 3 live servers (Notion, GitHub, Gmail). The LLM doesn't know or care which backend served a tool.
- **Blocks 3+ step tasks without a plan.** `plan_node` counts imperative features; 3+ without a plan in `tasks/todo.md` → hard block with a clear Telegram message. "Just do it" bypasses (logged WARN).
- **Spawns subagents for parallel work.** `delegate_task` shells out to a claude-code subprocess in a sandbox; the parent bot reports back without blocking the chat.
- **Runs on a schedule.** The cron scheduler fires isolated agent turns (e.g. daily homelab health check) and delivers the result to Telegram. Captain can also create/list/pause/resume jobs by chatting.
- **Audits everything.** Every tool call, compaction, subagent dispatch, and cron run goes to an append-only SQLite log — traceable even after context is compacted.

## Architecture

```
User (Telegram · Discord)
   ↓
Channel Router  ← pending_confirmations (clarify), reply routing
   ↓
Session Manager ← SQLite (data/sessions.db)
   ↓
Agent Runtime ← ReAct loop, MAX_TOOL_ROUNDS=5, streaming
   ├→ Context Builder   ← brain layer (SOUL+IDENTITY+WORKFLOW+MEMORY+USER) always-on
   │                       + JIT skills/todo/memory notes, token-budget trim
   ├→ Plan Node          ← hard block on 3+ step task without plan
   ├→ Compaction         ← model-aware threshold (off by default)
   └→ Ollama (OpenAI-compat) ← local + cloud fallback
   ↓ (if tool_use)
Tool Registry ← merged tool list (skills + inline + MCP)
   ├→ Skill Loader      ← scans workspace/skills/, parses SKILL.md, hot-reload
   ├→ Inline Tools      ← terminal, file, web, todo, clarify, delegate_task
   └→ MCP Client        ← stdio servers: notion (2), github (26), gmail (4) tools
   ↓
Memory ← SQLite (data/memory.db), note:* namespace injected into system prompt
Cron Scheduler ← asyncio loop, SQLite job store, delivers to Telegram/Discord
```

Reference: [`references/tiny-openclaw/`](references/tiny-openclaw/) (8-file Tiny-OpenClaw source, pinned commit `a4cb8cb9`).

## Tools

**8 doctrine skills** (prose-only, auto-loaded from `workspace/skills/` as `read_skill_<name>`): caveman, homelab-deploy, homelab-health, homelab-scaffold, nano-banana-pro (image gen), notion (deprecated), openclaw-health, project-init.

**5 inline tools** (real Python, registered in `agent_runtime.py`):

| Tool | File | What it does | Safety rails |
|---|---|---|---|
| `terminal` | `tools/terminal.py` | Run shell commands | Allowlist + Captain confirm for destructive, no `shell=True`, 30s timeout, 50KB cap, `~` expands |
| `file` | `tools/file.py` | `read_file` / `write_file` / `list_dir` | `WorkspaceBoundTool` allowlist, binary rejected, UTF-8, confirm overwrite |
| `web` | `tools/web.py` | `web_search` (DuckDuckGo) + `web_fetch` (httpx) | Robots.txt respected, 10s/30s timeouts, UA header |
| `todo` | `tools/todo.py` | `todo_read` / `todo_write` / `todo_add` | Workspace allowlist, Markdown |
| `clarify` | `tools/clarify.py` | Pause ReAct, ask Captain, resume | 1-per-iteration + 3-per-session caps, 5min timeout |
| `delegate_task` | `subagent/tool.py` | Spawn claude-code subprocess | Sandbox in `/tmp/aureon-subagent-<uuid8>/`, token cost control, 5min timeout, audit log |

**MCP servers** (stdio child processes, tools merged into the registry):

| Server | Tools | Auth | Status |
|---|---|---|---|
| **Notion** (`notion-mcp-server` v2.12.0) | `mcp_notion_notion_execute`, `mcp_notion_notion_describe` | `NOTION_TOKEN` (from hermes `NOTION_API_KEY`) | ✅ live |
| **GitHub** (`@modelcontextprotocol/server-github`) | 26 (`mcp_github_*`) | `GITHUB_TOKEN` (read-only v1) | ✅ live |
| **Gmail** (`oliverkoast/multi-email-mcp` v0.1.0) | `mcp_gmail_search_mail`, `_read_message`, `_list_recent`, `_list_accounts` | OAuth 2.0 `gmail.readonly` (token in `tokens/vishal.json`) | ✅ live |

See [`tasks/aureon-agent gmail mcp.md`](tasks/aureon-agent%20gmail%20mcp.md) for the full Gmail OAuth walkthrough, and [`tasks/aureon-agent metal model.md`](tasks/aureon-agent%20metal%20model.md) for the deep architecture mental model.

## Cron scheduler

A background asyncio loop inside the bot process runs isolated agent turns on a schedule and delivers output to Telegram/Discord. Jobs are stored in SQLite (`data/cron_jobs.db`), support cron/interval/at schedules (croniter), and stagger to top-of-hour.

```bash
# via CLI
aureon-agent cron create --name health --schedule "0 8 * * *" --prompt "run homelab-health" --deliver telegram
aureon-agent cron list
aureon-agent cron remove <id>

# or just tell the bot on Telegram:
# "create a daily health check cron at 8am"
# "list my cron jobs"  → cron_create / cron_list / cron_remove / cron_pause / cron_resume tools
```

Verified live: `homelab-health-daily` (`0 8 * * *`, skill `homelab-health`, deliver telegram) matches the Hermes job `bcfd979f8bd0`.

## Setup modes

| Mode | Behavior | Use for |
|---|---|---|
| `aureon-agent setup` | Interactive wizard, shows current values as defaults | First install, full reconfigure |
| `aureon-agent setup --quick` | Only prompts for missing/unset | "I just changed one thing" |
| `aureon-agent setup --non-interactive` | Uses defaults + env vars, no prompts | CI, scripts, automation |
| `aureon-agent setup --reset` | Wipes `.env` via `trash`, runs fresh | Start over cleanly |
| `aureon-agent setup --section <name>` | Re-runs one section | Change one channel, swap LLM, etc. |

Sections: `model | channel | daemon | skills | workspace | all`.

## MCP: adding a new server

MCP servers are **additive** — local doctrine skills stay forever; MCP is for new external services only. The Agent Runtime merges both registries at boot. To add a server:

1. Install the npm package globally (`npm install -g <pkg>`).
2. Add a block in `aureon_agent/cli.py:_parse_mcp_servers()` — command `node` + **absolute path** to the server binary (systemd PATH lacks `~/.npm-global/bin`), plus the env map (secrets via `env=` param, never on the network).
3. Add a `check_mcp_servers()` entry in `aureon_agent/doctor.py`.
4. Verify: `aureon-agent mcp list` → server shows `connected` with its tools.
5. Live-test with a real agent turn (not just a mocked test).

Auth model: **stdio** servers get secrets via subprocess `env=`; **HTTP/SSE** servers hold secrets themselves and the agent only needs the URL.

## Safety

- **No `0.0.0.0` binds.** Localhost or Tailscale only.
- **Telegram chat ID allowlist.** Drop messages from non-allowed chats silently.
- **Caveman mode always-on** in replies (per `agent.environment_hint` + SOUL.md).
- **Plan-node hard block** on 3+ step tasks without a plan — prevents scope creep.
- **Read-only MCP by default** — GitHub/Gmail are read-only v1; no write ops until explicitly enabled.
- **OAuth, not plaintext** — Gmail uses OAuth 2.0 with a cached refresh token; the mailbox password is never stored.
- **Scope discipline** — write what was asked, stop, don't add scope.

## Project layout

```
aureon-agent/
├── main.py                 # back-compat shim
├── pyproject.toml          # console scripts: aureon-agent, aureon-agent-setup, ...
├── aureon_agent/           # main package
│   ├── cli.py              # run bot, MCP server wiring, cron start/stop
│   ├── setup.py            # interactive wizard
│   ├── doctor.py           # health check
│   ├── postinstall.py      # dep bootstrap
│   ├── config.py           # typed AureonConfig + .env IO
│   ├── context_builder.py  # layered brain + JIT context
│   ├── plan_node.py        # 3+ step task hard block
│   ├── cron.py             # asyncio scheduler
│   ├── cron_db.py / cron_schedule.py / cron_cli.py
│   ├── mcp_client.py       # stdio MCP connection manager
│   ├── tool_registry.py    # merges skills + inline + MCP
│   ├── tui.py              # Rich + Questionary helpers (pixel-art banner)
│   └── tools/              # terminal, file, web, todo, clarify
├── channels/               # base.py, router.py, telegram.py, discord.py
├── subagent/               # tool.py (delegate_task)
├── assets/
│   └── banner.svg          # THIS banner
├── scripts/
│   └── generate_banner.py
├── tests/                  # smoke.py, test_agent_loop.py, test_cron.py, test_mcp_*.py, ...
├── references/
│   └── tiny-openclaw/      # vendored reference (pinned)
├── workspace/              # symlinks → ~/.openclaw/workspace/ (doctrine)
├── workflow/               # symlink → ~/dev-shared/workflow/ (shared)
├── docs/                   # setup-script.md, mcp-decision.md, cron.md
├── tasks/                  # DEVLOG.md, todo.md, lessons.md, mental-model docs
├── tokens/                 # gitignored — OAuth tokens (gmail/vishal.json)
└── .env                    # gitignored — secrets (chmod 600)
```

## Status

**v0.4 (current)** — Phase 0-9.5 complete. MCP (Notion/GitHub/Gmail) live + verified. See [`tasks/todo.md`](tasks/todo.md) for the full roadmap.

- ✅ Live Telegram round-trip verified end-to-end
- ✅ Doctrine brain layer loaded every turn (SOUL+IDENTITY+WORKFLOW+MEMORY+USER)
- ✅ 18 tools: 8 doctrine skills + 5 inline + 1 subagent + MCP (Notion 2 / GitHub 26 / Gmail 4)
- ✅ Plan-node hard block on 3+ step tasks
- ✅ Subagent dispatch (claude-code sandbox)
- ✅ Cron scheduler live (CLI + chat tools)
- ✅ Layered context builder (brain always-on, JIT bounded)
- ✅ systemd user service (auto-restart, survives logout/reboot, PID lock)
- ✅ 3 MCP servers live + verified against real APIs
- ✅ 77/77 tests pass
- ⏳ Filesystem MCP (Phase 7.5) — pending
- ⏳ Homelab MCP (Phase 7.6, roll our own) — pending
- ⏳ Webhook mode for Telegram (replace polling) — pending
- ⏳ Server/group channel support (per-channel tool policy) — pending

## Development

```bash
# run tests
source .venv/bin/activate
python tests/smoke.py
python -m pytest tests/ -q

# inspect MCP servers + tools
aureon-agent mcp list

# regenerate the banner (after font/color changes)
python scripts/generate_banner.py

# health check
aureon-agent doctor
```

See [`CLAUDE.md`](CLAUDE.md) for the project context block, [`CONTEXT.md`](CONTEXT.md) for the stack snapshot, and [`AGENTS.md`](AGENTS.md) for the 6-rule per-project contract.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

- [ashishbamania/Tiny-OpenClaw](https://github.com/ashishbamania/Tiny-OpenClaw) — 8-component reference architecture, vendored at `references/tiny-openclaw/`
- [ashishbamania/Into-AI](https://substack.com/home/post/p-193348119) — the build walkthrough that became the reference port
- [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) — GitHub MCP server
- [oliverkoast/multi-email-mcp](https://github.com/oliverkoast/multi-email-mcp) — Gmail OAuth MCP server
- [shellygo/notion-mcp-server](https://github.com/shellygo/notion-mcp-server) — Notion MCP server
