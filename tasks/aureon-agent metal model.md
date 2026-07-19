# Mental model: aureon-agent

> Last updated: 2026-07-18 (post Phase 7.1/7.3 MCP, Phase 9 cron, rich `/status`, Telegram slash commands, invoice auto-downloader).
> Docs-only refresh. Architecture verified against live box (v0.5.1, 111 tests, 57-tool registry).

## Architecture: aureon-agent vs tiny-openclaw

```
┌─────────────────────────────────────────────────────────────────┐
│ tiny-openclaw (vendored reference, 8 files, 330 LoC)           │
│ • Anthropic-only, JSON file storage                              │
│ • No streaming, no skills, no doctrine, no subagent             │
│ • No MCP, no cron, no plan-node                                 │
└─────────────────────────────────────────────────────────────────┘
                              ↓  vendored at references/tiny-openclaw/
┌─────────────────────────────────────────────────────────────────┐
│ aureon-agent (production, 2000+ LoC, 11+ modules)                │
│                                                                  │
│  Channels (interface layer)  ← channels/                        │
│  ┌──────────────────┐  ┌──────────────────┐                     │
│  │ Telegram adapter │  │ Discord adapter  │                     │
│  │ (polling, edit,  │  │ (DM-only v1)     │                     │
│  │  /slash cmds)    │  │                   │                     │
│  └────────┬─────────┘  └────────┬─────────┘                     │
│           └─────────────────┬──────┘  base.py / router.py        │
│                             │   telegram.py / discord.py         │
│  ┌──────────────────────────▼──────────────────────────┐       │
│  │ ChannelRouter  ← pending_confirmations (clarify)     │       │
│  │                ← /slash command routing             │       │
│  └──────────────────────────┬──────────────────────────┘       │
│                             │                                    │
│  Agent Runtime (orchestrator)  ← agent_runtime.py              │
│  ┌──────────────────────────▼──────────────────────────┐     │
│  │ AgentRuntime.run(user_message, session_id, callbacks)│     │
│  │  1. require_plan()      ← plan_node v2 (hard block)  │     │
│  │  2. _maybe_compact()    ← model-aware compaction     │     │
│  │  3. ContextBuilder.build()  ← 5 brain files + JIT    │     │
│  │  4. ReAct loop (MAX_TOOL_ROUNDS=5):                  │     │
│  │     tool = tool_registry.dispatch(name)  ← 57 tools │     │
│  │     clarify → pause/await  delegate_task → subprocess│    │
│  │     cron_* → cron_db      mcp_* → MCPManager         │     │
│  │  5. sessions.add_message(assistant, response)        │     │
│  └──────────────────────────┬──────────────────────────┘     │
│                             │                                    │
│  Tool Registry (57 tools)   ← tool_registry.py                 │
│  ┌──────────────────────────▼──────────────────────────┐     │
│  │ 3-tier merge: skills(8) → inline(16) → MCP(33)      │     │
│  │ • 8 doctrine skills: read_skill_<name>              │     │
│  │ • 16 inline (Python): terminal, file×3, web×2,       │     │
│  │     todo×3, clarify, delegate_task, cron×5          │     │
│  │ • 33 MCP (stdio servers):                            │     │
│  │     notion×2, github×26, gmail×5                    │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                                  │
│  MCP layer (stdio subprocesses)  ← mcp_client.py/MCPManager    │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ notion-mcp-server (2 tools)        NOTION_TOKEN     │     │
│  │ @modelcontextprotocol/server-github (26) GITHUB_*   │     │
│  │ multi-email-mcp / gmail-api (5)   Gmail OAuth2     │     │
│  │   tools prefixed mcp_<server>_<tool>                │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                                  │
│  Cron Scheduler (recurrence)  ← cron.py / cron_db.py           │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ CronScheduler ticks every 60s inside the bot process│     │
│  │ Due job → isolated session cron:<id>:<ts>           │     │
│  │ → AgentRuntime.run(prompt) → deliver to Telegram    │     │
│  │ Jobs in data/cron_jobs.db (survive restart)         │     │
│  │ e.g. invoice-weekly (0 9 * * 1 Europe/Berlin)      │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                                  │
│  Storage (persistence)  ← aiosqlite WAL                        │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ data/sessions.db        full history (view-layer)   │     │
│  │ data/memory.db          key-value note:* namespace  │     │
│  │ data/cron_jobs.db       cron_jobs + cron_runs       │     │
│  │ data/compaction_log.db  append-only audit           │     │
│  │ data/tool_log.db        append-only audit           │     │
│  │ data/subagent_log.db    append-only audit           │     │
│  │ ~/.cache/aureon-agent.pid  PID lock                 │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                                  │
│  Doctrine (symlinked, not copied)                               │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ workspace/ → ~/.openclaw/workspace/  (SOUL,USER,     │     │
│  │   IDENTITY, WORKFLOW, MEMORY, skills/, memory/)      │     │
│  │ workflow/ → ~/dev-shared/workflow/  (gitignored)    │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                                  │
│  CLI (operator surface)  +  Telegram /slash commands            │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ aureon-agent → python -m aureon_agent                │     │
│  │   setup|postinstall|doctor|start|stop|status|logs    │     │
│  │   version|sessions|mcp list|cron <sub>|tool-log|     │     │
│  │   clarify-log|subagent-log|compaction-log            │     │
│  │ Telegram: /sessions /doctor /status /cron /mcp      │     │
│  │            /logs /version /help                      │     │
│  └─────────────────────────────────────────────────────┘     │
│                                                                  │
│  Process management  ← systemd user service                    │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ ~/.config/systemd/user/aureon-agent.service         │     │
│  │ Restart=on-failure, RestartSec=10, enable-linger    │     │
│  │ PID lock ~/.cache/aureon-agent.pid (no Telegram 409)│     │
│  └─────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

---

## The 57 tools in detail

The registry merges **3 tiers** (skills → inline → MCP; last wins on name collision, WARN logged). Total = **57 tools**.

### Tier 1 — 8 doctrine skills (prose-only, synthesized `read_skill_<name>`)

Each returns the SKILL.md body on demand. Auto-loaded from `workspace/skills/`.

| Tool | Purpose | Trigger |
|---|---|---|
| `read_skill_caveman` | Compressed reply mode (~75% token savings) | Auto via `agent.environment_hint` |
| `read_skill_homelab-deploy` | Tailscale sidecar deploy | "deploy" |
| `read_skill_homelab-health` | Health-check homelab | "health" |
| `read_skill_homelab-scaffold` | New service from template | "scaffold" |
| `read_skill_nano-banana-pro` | Image generation (Google) | "image" |
| `read_skill_notion` | Read/write Notion (deprecated) | "notion" |
| `read_skill_openclaw-health` | OpenClaw integrity | "doctrine" |
| `read_skill_project-init` | New project dev setup | "project" |

### Tier 2 — 16 inline tools (real Python, registered in `agent_runtime.py`)

| Tool | File | What it does | Safety rails |
|---|---|---|---|
| `terminal` | `tools/terminal.py` | Shell commands (string or list) | Allowlist + Captain confirm for destructive, no `shell=True`, 30s timeout, 50KB cap, `~` expand |
| `file` | `tools/file.py` | `read_file`/`write_file`/`list_dir` | `WorkspaceBoundTool` allowlist, binary rejected, confirm overwrite |
| `web` | `tools/web.py` | `web_search` (DDG) + `web_fetch` (httpx) | robots.txt, UA header, 10s/30s timeouts |
| `todo` | `tools/todo.py` | `todo_read`/`todo_write`/`todo_add` | Workspace allowlist, Markdown |
| `clarify` | `tools/clarify.py` | Pause ReAct, ask Captain, resume | 1/iter + 3/session cap, 5min timeout |
| `delegate_task` | `subagent/tool.py` | Spawn claude-code subprocess | Sandbox `/tmp/aureon-subagent-<uuid>/`, 50K token cap, audit log |
| `cron_create` | `agent_runtime.py` | Create cron job (DB write) | Defaults chat to allowed chats |
| `cron_list` | `agent_runtime.py` | List cron jobs | Reads `cron_jobs.db` |
| `cron_remove` | `agent_runtime.py` | Delete cron job | DB update |
| `cron_pause` | `agent_runtime.py` | Disable job | DB update |
| `cron_resume` | `agent_runtime.py` | Enable job | DB update |

(5 cron tools share `cron_db.py` + `cron_schedule.py` with the CLI.)

### Tier 3 — 33 MCP tools (stdio subprocess servers, prefixed `mcp_<server>_<tool>`)

| Server | Tools | Config (env) | Auth |
|---|---|---|---|
| `notion` | 2 (`notion_execute`, `notion_describe`) | `NOTION_TOKEN` | API key |
| `github` | 26 (`mcp_github_*`) | `GITHUB_TOKEN`/`GITHUB_MCP_TOKEN` | PAT |
| `gmail` | 5 (`search_mail`, `read_message`, `list_recent`, `list_accounts`, `download_attachment`) | `GOOGLE_OAUTH_CLIENT_ID/SECRET` | OAuth 2.0 `gmail.readonly`, refresh token in `tokens/vishal.json` (gitignored) |

MCP tools call the stdio server via `MCPManager.call_tool()`. Server crash → error dict returned, **no agent crash** (graceful). `doctor.check_mcp_servers()` verifies all 3 configured.

---

## How a Telegram message flows end-to-end

```
1. Captain sends "download my recent invoices from gmail" to @aureon_agent_bot

2. Telegram → POST getUpdates (polled ~10s by the bot process)

3. channels/telegram.py:_on_message
   - chat_id not in allowed_chats → drop silently
   - text.startswith("/") → route to _on_command (slash surface, no LLM)
   - else → router.handle_message("telegram", chat_id, text, callbacks)

4. router → sessions.get_or_create_session("telegram:723865496")
   → sessions.add_message("user", text)

5. agent_runtime.run(user_message):
   a) require_plan(): 3+ step + no plan → hard block (unless "just do it")
   b) _maybe_compact(history, system_prompt): model-aware, off by default
   c) ContextBuilder.build(): 5 brain files (SOUL+IDENTITY+WORKFLOW+MEMORY+USER)
      + JIT sections, token-budget trimmed (brain protected)
   d) ReAct loop (5 rounds):
      Round 1: LLM → tool_call mcp_gmail_search_mail(query=...)
      Round 2: LLM → mcp_gmail_read_message(id=...)  (surfaces attachmentId)
      Round 3: LLM → mcp_gmail_download_attachment(...) → writes %PDF
      Round 4: LLM → text summary
   e) sessions.add_message("assistant", response)

6. telegram.py edits placeholder via editMessageText (1/sec throttle);
   long replies chunked at 4096 chars.
```

### A `/slash` command (no LLM)

```
Captain: /status  → _on_message routes to _on_command
  → subprocess: python -m aureon_agent status
  → captured stdout wrapped in ``` MarkdownV2 code block ```
  → send_message(parse_mode="MarkdownV2")
  → Telegram renders aligned monospace (Rich tables don't break)
```

---

## Cron scheduler (recurrence)

**Lives inside the bot process** (`CronScheduler` in `cron.py`), ticks every 60s.

- Jobs persist in `data/cron_jobs.db` (`cron_jobs` + `cron_runs` tables, WAL). Survive restart.
- `_run_job()`: builds an **isolated** session `cron:<job_id>:<ts>` (no chat history), runs `AgentRuntime.run(prompt)` with `asyncio.wait_for(timeout)`, delivers output to Telegram, then reschedules (`next_run_at` recomputed) or auto-deletes (one-shot).
- Schedule types: `cron` (5-field Vixie via croniter), `interval` (Nm/Nh/Nd), `at` (ISO). Timezone via zoneinfo. Top-of-hour stagger (0-5 min) for `:00` crons.
- **CLI:** `aureon-agent cron list|create|pause|resume|run|remove|runs|status` (all accept job **name or ID** since the name-resolution fix).
- **Agent tools:** `cron_create/list/remove/pause/resume` (same DB, no duplication).
- **Example job:** `invoice-weekly` (`0 9 * * 1` Europe/Berlin) — prompt drives the gmail MCP tools as an agent turn, delivers a Telegram summary of downloaded invoices.

---

## Invoice auto-downloader (interview prototype)

Three engines on one Gmail OAuth base, scoped to `~/dev-shared/docs/invoices/`:

| Engine | What | When |
|---|---|---|
| **A** — `invoice_pilot.py` | Standalone script (no agent). Search-first query, throttled batches, 429 backoff, `.seen.json` checkpoint, `--dry-run`/`--incremental` | Bulk backfill (grabbed 84+ PDFs from ~6500 emails) |
| **B** — MCP patch | Patched `multi-email-mcp` `gmail-api.js` (surface `attachmentId`, new `download_attachment` + 429 backoff). Agent drives `search_mail→read_message→download_attachment` | Live agent/Telegram requests |
| **C** — cron `invoice-weekly` | Agent-native recurrence (above). **The only retained scheduler** — the standalone systemd timer was dropped (didn't fit the agent workflow) | Weekly Mon 09:00 |

Detection = 3-layer heuristic (subject/snippet/body token OR `--strict` filename gate). All 85 downloaded PDFs are valid `%PDF`, dedup via `.seen.json` + in-place overwrite.

---

## The 5 SQLite databases

| DB | Schema | Purpose | Mutability |
|---|---|---|---|
| `data/sessions.db` | `sessions` + `messages(id, session_id, role, content, idx)` | Conversation history | View-layer only (compaction never rewrites) |
| `data/memory.db` | `memory(key PK, value, updated_at)` | Key-value `note:*` namespace | Intentional |
| `data/cron_jobs.db` | `cron_jobs` + `cron_runs` | Cron persistence | Intentional |
| `data/compaction_log.db` | `compaction_runs(...)` | Audit: when/tokens/summary/model | Append-only |
| `data/tool_log.db` | `tool_calls(...)` | Audit: every tool call | Append-only |
| `data/subagent_log.db` | `dispatch_log(...)` | Audit: every subagent dispatch | Append-only |

3 audit logs are append-only → full traceability even after compaction/session wipe.

---

## Rich `/status` + Doctor (operator health)

- **`/status`** (`aureon_agent/status.py`, `cmd_status`): `gather_status()` → plain dict, **never raises** (systemctl/git/db absent → `n/a`); `render_status()` formats a 5-section Rich block:
  1. Service + uptime (service + system)
  2. Runtime/model (active model, key presence only `set`/`none`, fallbacks, execution/runtime/think/fast)
  3. Tokens/context (session estimate, context used/total %, compactions)
  4. Session (most-recent session id, msgs, last active)
  5. Cron + MCP (job counts, 3-server MCP summary via `doctor.check_mcp_servers`)
- **Doctor TUI** (`doctor.py`): health checks — Python, venv, `.env` perms, workspace symlinks, 5 brain files, tools allowlist, Claude CLI, plan node, Ollama, Telegram, systemd, cron scheduler, MCP (notion/github/gmail), compaction log, model-known. **Now reports all 3 MCP servers** (gmail was missing — fixed to read `GOOGLE_OAUTH_*`).
- **Version** sourced from `aureon_agent.__version__` (currently `0.5.1`); banner/doctor/status/version all read it (one bump fixes the stale `v0.1.0` header).

### Telegram `/slash` commands

Routed in `_on_message` (PTB's `CommandHandler` entity-matching was unreliable for API-sent commands). Each shells out to the CLI and wraps output in a **MarkdownV2 fenced code block** (fixes Rich tables breaking in chat):

`/sessions` `/doctor` `/status` `/cron` `/mcp` `/logs` `/version` `/help`

---

## The process model

**Two ways to run:**
1. Foreground (dev): `python -m aureon_agent` or `aureon-agent start`
2. Background (prod): systemd user service, PID file `~/.cache/aureon-agent.pid`

**Why systemd:** auto-restart on crash, survives logout (`enable-linger`), survives reboot, journald logs, PID lock prevents Telegram 409.

---

## What's been shipped (vs the old "NOT in v1" list)

✅ Done: MCP integration (notion+github+gmail), cron scheduler + `invoice-weekly`, rich `/status`, Telegram slash commands, invoice auto-downloader (85 PDFs), context-builder rewrite (5 brain files), session compaction, plan-node hard block, subagent dispatch, PID lock + systemd, doctor TUI (3 MCP servers).

**Still pending (next-phase work):**
- Webhook mode for Telegram (replace polling)
- Server/group channel support (per-channel tool policy)
- Phase 7.5 Filesystem MCP, 7.6 Homelab MCP
- Live-channel compaction round-trip test (verified via direct calls only)

---

## Files you'd touch to extend

| Want to... | Edit |
|---|---|
| Add a tool | `aureon_agent/tools/<name>.py` (inherit `WorkspaceBoundTool`) or `agent_runtime.py` inline schema; register in `setup_registry()` |
| Add a doctrine skill | Drop `SKILL.md` in `~/.openclaw/workspace/skills/<name>/`; restart/hot-reload |
| Add an MCP server | `cli.py:_parse_mcp_servers()` + `doctor.py` check + `mcp_client.py` (already generic) |
| Add a cron job | `scripts/seed-*.sh` or `aureon-agent cron create` (agent can do it via `cron_create`) |
| Change compaction | `aureon_agent/models.py` (windows) or `compaction/threshold.py` |
| Change identity | `~/.openclaw/workspace/` (SOUL/IDENTITY/etc.) — symlinked, not in repo |
| Change LLM | `aureon_agent/cli.py` + `AureonConfig` |

---

## TL;DR

aureon-agent is a Hermes-flavored autonomous AI agent that:
- Lives on athena, runs as a systemd user service (PID-locked, no Telegram 409)
- Talks to Captain on Telegram; **slash commands** (`/status` `/sessions` `/doctor` `/cron` `/mcp` `/logs` `/version` `/help`) self-serve health without SSH
- Loads doctrine from symlinked `~/.openclaw/workspace/`
- **57 tools**: 8 doctrine skills + 16 inline + 33 MCP (notion/github/gmail)
- Has a **cron scheduler** inside the bot (e.g. weekly `invoice-weekly` invoice download)
- Blocks 3+ step tasks without a plan, asks clarifying questions, spawns subagents
- Compacts long sessions (model-aware, off by default), audits every action to 3 SQLite logs
- Never loses conversation history (view-layer compaction only)
- v0.5.1, 111 tests passing, ruff clean

It's well past tiny-openclaw parity and now has MCP + cron + recurrence + a self-serve operator surface.
