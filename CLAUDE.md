# CLAUDE.md
> This file provides guidance to Claude Code (claude.ai/code) when working on this repository.
> Project-specific instructions. Workflow conventions live in `./workflow/`.

---

## Session startup

Before any meaningful work, read these files in order:

1. `CONTEXT.md` — stack, infra, design tokens, decision log
2. `tasks/DEVLOG.md` (last 3 entries) — current world state
3. `tasks/todo.md` — phased rollout (5 phases, 14 sub-tasks)
4. `tasks/lessons.md` — active prevention rules
5. `tasks/kickoff-aureon-agent.md` — the full spec for this project (read after the 4 above)

**This project runs in the dual-session model** (see `workflow/SESSION-WORKFLOW.md` v3):

- **Local session** (this is normally the one you are): `[aureon-agent]-local`
  - Host: athena tmux
  - Process: Claude CLI on athena, started with `claude --remote-control '[aureon-agent]-local'`
  - Branch: whatever the working dir has checked out (work on `feat/<task>` sub-branches off `dev` or `main`)
  - Filesystem: full local access (athena's `/home/radxa/...`, Docker, Ollama, Telegram bot tokens, Discord bot tokens)
  - Use for: agent runtime dev, file edits, SQLite inspection, Telegram/Discord channel testing, anything needing local FS, secrets, or running services
- **Cloud session** (sibling, ephemeral): `[aureon-agent]-cloud`
  - Host: Anthropic cloud container (NOT your machine)
  - Process: started from https://claude.ai/code → Code tab → New session → pick repo → pick the sub-branch the local session is working on
  - Branch: same as the local session (both share the working dir on the repo; no separate lineage branches)
  - Filesystem: **ONLY the GitHub repo** (no `~/dev-shared/`, no Docker, no `.env`, no running services)
  - Use for: skill load tests, sqlite3 schema review, ruff lint, full e2e audit, anything needing CPU isolation
  - **Cannot do:** access Ollama, send Telegram/Discord messages, read `.env` (no secrets in cloud), inspect running bot, hit Tailscale IPs

**No branch setup needed.** Both sessions share `dev` (or `main`) and work on `feat/<task>` sub-branches directly. There are no `claude/local` / `claude/cloud` lineage branches — that pattern was tried and removed (see L-069 in `tasks/lessons.md`).

**How to start the cloud session:** open https://claude.ai/code → Code tab → New session → pick `vkkatariya/aureon-agent` → pick the sub-branch the local session is working on → rename to `[aureon-agent]-cloud`. The cloud session spins up in an Anthropic container with a fresh clone.

**Cross-session handoff:** read top 3 of `tasks/DEVLOG.md` on every resume — the cloud and local sessions log to the same DEVLOG with `cloud-session-start` / `cloud-session-end` / `local-session-handoff` markers so the other side knows what happened. Coordination also happens via git branches and PRs.

## Doctrine source of truth

This project loads its agent identity, user preferences, and workflow doctrine from `~/.openclaw/workspace/` via symlinks in `workspace/`. The symlinks are part of the repo (so doctrine is versioned alongside the code), but the underlying files live outside this repo.

```
workspace/
├── SOUL.md            → ~/.openclaw/workspace/SOUL.md         (caveman always-on, agent identity)
├── USER.md            → ~/.openclaw/workspace/USER.md         (Captain = Vishal, TZ Europe/Berlin)
├── IDENTITY.md        → ~/.openclaw/workspace/IDENTITY.md     (Aureon 🦾, 4 modes)
├── WORKFLOW.md        → ~/.openclaw/workspace/WORKFLOW.md     (6-rule execution protocol)
├── MENTAL-MODEL-TEMPLATE.md → ~/.openclaw/workspace/MENTAL-MODEL-TEMPLATE.md
├── MEMORY.md          → ~/.openclaw/workspace/MEMORY.md       (Olympus orchestration, agent roster, lessons)
├── HEARTBEAT.md       → ~/.openclaw/workspace/HEARTBEAT.md
├── channel-policy-spec.md → ~/.openclaw/workspace/channel-policy-spec.md
├── handoff-template.md → ~/.openclaw/workspace/handoff-template.md
├── skills/            → ~/.openclaw/workspace/skills/        (8 doctrine skills)
├── memory/            → ~/.openclaw/workspace/memory/        (daily notes)
└── tasks/
    ├── todo.md        (own copy — Captain's active work)
    └── lessons.md     (own copy — append on correction)
```

**To edit doctrine:** edit the source at `~/.openclaw/workspace/`, not the symlinks. Symlinks just resolve; the source files live outside this repo. If symlinks are broken on a fresh clone, see `README.md` §"Workspace" for the restore snippet.

## Workflow references (symlinked, homelab-only)

The `./workflow/` directory is a symlink to `~/dev-shared/workflow/` — same path on every machine via mutagen sync. **Do not commit it** (already in `.gitignore`). Read workflow files on demand, not at every session start:

- `./workflow/SESSION-WORKFLOW.md` — Claude Code session lifecycle, dual-session (local + cloud), no lineage branches, /remote-control, compaction
- `./workflow/AI-ROUTING.md` — L1/L2/L3 layer model, tool vs agent routing
- `./workflow/GIT-GITHUB-BLUEPRINT.md` — branch/commit/PR conventions
- `./workflow/agents_workflow/AI-AGENTS-ORCHESTRATION.md` — sub-agent dispatch patterns
- `./workflow/CLAUDE-MD-TEMPLATE.md` — canonical template for new project CLAUDE.md files
- `./workflow/TODAY.md` — daily task list
- `./workflow/PROJECTS.md` — cross-project statuses

If the symlink is broken on a fresh clone, recreate it:
```bash
ln -sf ~/dev-shared/workflow ./workflow
```

## Compaction + /remote-control (project-specific)

- **/remote-control** is the real command (not `/rc` — that's hallucinated)
- **Before manual /compact:** commit, push, append your work-in-progress to `tasks/DEVLOG.md`
- **After /compact** or /clear: re-read top 3 of `tasks/DEVLOG.md`, re-read this CLAUDE.md, check `git status` to reconstruct in-flight work
- **Pro plan 5hr rolling limit:** dual session uses 2 surfaces in parallel. Heavy work (full test suite, e2e audit) in cloud; agent runtime dev + channel testing in local (needs running services)

---

## Commands

### Local dev (Python 3.12, venv)
```bash
cd ~/dev-shared/projects/aureon-agent
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Run the agent (after Phase 4 main.py is written)
python main.py

# Run tests (after Phase 5 tests are written)
python tests/smoke.py
python tests/test_agent_loop.py
```

### Skill + doctrine inspection
```bash
# List loaded skills
ls workspace/skills/

# Check doctrine source
ls -la ~/.openclaw/workspace/

# Read Captain's active todo
cat workspace/tasks/todo.md

# Check workspace symlinks resolve
for f in workspace/*.md workspace/skills workspace/memory; do
  test -e "$f" && echo "  ✓ $f → $(readlink $f)" || echo "  ✗ $f BROKEN"
done
```

### Database (SQLite, gitignored)
```bash
# Inspect sessions DB
sqlite3 data/sessions.db ".tables"
sqlite3 data/sessions.db "SELECT * FROM sessions LIMIT 5;"

# Inspect memory DB
sqlite3 data/memory.db "SELECT * FROM notes LIMIT 5;"

# Reset DBs (DESTRUCTIVE — ask first)
rm data/*.db data/*.db-wal data/*.db-shm
```

### Invoice auto-downloader (`feat/invoice-pilot`)
```bash
# Engine A — standalone Gmail invoice downloader (deps: requirements-invoice.txt)
pip install -r requirements-invoice.txt
python invoice_pilot.py --dry-run                 # list candidates, download nothing
python invoice_pilot.py --after 2026/01/01        # scoped real run
python invoice_pilot.py --incremental             # weekly window (90d first, 7d after)
python invoice_pilot.py --strict                  # require invoice token in filename too
# saves to ~/dev-shared/docs/invoices/ (override: --dir or INVOICE_DIR)

# Engine B — MCP patch (agent-driven download via multi-email-mcp)
./mcp-patches/apply.sh                             # patch the global MCP server
node tests/mcp_gmail_download.test.mjs             # deterministic patch smoke (no network)
python live_test_gmail_download.py                 # live: real Gmail -> real invoice PDF

# Engine C variant 1 — weekly systemd timer (deterministic script + .seen dedup)
cp systemd/aureon-invoice.{service,timer} ~/.config/systemd/user/
systemctl --user enable --now aureon-invoice.timer
systemctl --user start aureon-invoice.service      # trigger a run manually

# Engine C variant 2 — aureon agent-scheduler job (LLM drives the MCP tools)
./scripts/seed-invoice-cron.sh                     # register the weekly cron job
python -m aureon_agent cron list                   # confirm invoice-weekly present
python -m aureon_agent cron run <job_id>           # queue for the running bot's next tick
python live_test_invoice_cron.py                   # out-of-process live proof (no bot restart)
# NOTE: the running bot must be restarted once to load the patched
# download_attachment tool into its MCP subprocess.
```

### Channel testing (after Phase 3)
```bash
# Telegram: check bot token, then send a test message
echo "$TELEGRAM_BOT_TOKEN" | head -c 10
curl -s "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe"

# Discord: check bot token
curl -s -H "Authorization: Bot $DISCORD_BOT_TOKEN" https://discord.com/api/v10/users/@me
```

### CI (GitHub Actions, public repo)
```bash
# Trigger CI manually
gh workflow run ci.yml --ref dev

# Watch CI run
gh run watch
```

---

## Architecture

### Current phase: Phase 1 done, Phase 2 ready (SQLite Memory + SessionManager)

Personal AI agent with Ollama local + cloud fallback, doctrine-aware startup, and multi-channel (Telegram + Discord) support. Vendored reference at `references/tiny-openclaw/` (8 files, pinned commit `a4cb8cb94`).

### Stack

| Layer | Technology | Notes |
|---|---|---|
| Language | Python 3.12 | async-first |
| LLM | Ollama (OpenAI-compat) | `https://ollama.com/v1` for cloud, `http://127.0.0.1:11434/v1` for local |
| HTTP | `httpx` (async) | Ollama + tool calls |
| Telegram | `python-telegram-bot[rate-limiter]` | polling v1, webhook v2 |
| Discord | `discord.py` | DM-only v1, server v2 |
| DB | `aiosqlite` (WAL mode) | matches your local SQLite pattern |
| File watching | `watchfiles` | skill hot-reload |
| Config | `.env` via `python-dotenv` | standard, never committed |
| HTTP health | `aiohttp` (optional) | `127.0.0.1:7777/health` for systemd watchdog |

### Directory layout (target)

```
aureon-agent/
├── main.py                       # entry, env load, wire all components
├── agent_runtime.py              # ReAct loop, Ollama streaming, plan-node soft check
├── context_builder.py            # multi-source system prompt
├── memory.py                     # SQLite Memory (note:* + meta)
├── session_manager.py            # SQLite SessionManager
├── skill_loader.py               # SKILL.md format + hot-reload
├── plan_node.py                  # soft-warning helper
├── lessons.py                    # append to workspace/tasks/lessons.md
├── channels/
│   ├── base.py                   # Channel ABC
│   ├── router.py                 # ChannelRouter
│   ├── telegram.py               # Telegram adapter
│   └── discord.py                # Discord adapter
├── workspace/                    # symlinks to ~/.openclaw/workspace/
├── data/                         # gitignored: sessions.db, memory.db
├── tests/
│   ├── smoke.py
│   └── test_agent_loop.py
├── references/
│   └── tiny-openclaw/            # 8-file reference, pinned commit
├── .github/workflows/ci.yml      # Python 3.12, pip install, smoke + agent-loop tests
├── CLAUDE.md                     # this file
├── AGENTS.md                     # 6-rule per-project contract
├── CONTEXT.md                    # stack, infra, decisions
├── README.md                     # setup + run + workspace restore
├── requirements.txt              # deps
└── .gitignore                    # .env, *.db, __pycache__, workspace scratch dirs
```

### Branch strategy

- `main` — stable, deployable baseline
- `dev` — integration branch for reviewed features
- `feat/<slug>` / `fix/<slug>` — per-task work, branched off `dev`
- Conventional commits: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `style:`
- One task = one branch. Push before session end. PR against `dev`, not `main`.
- Captain's standing rule: keep work branches on remote after merge. Don't auto-delete remote branches.
- Force-push / destructive remote ref changes → ask first.

---

## Hard constraints (from `CONTEXT.md`)

- **No `0.0.0.0` binds.** Localhost or Tailscale only.
- **No force-push / destructive ops** without explicit confirmation. Captain says "go" before.
- **Telegram chat ID allowlist** via `TELEGRAM_ALLOWED_CHATS` env. Drop non-allowed messages silently.
- **Caveman mode always-on** in replies (per `agent.environment_hint` + SOUL.md `caveman-begin/end` block).
- **Scope discipline** — write what was asked, stop, don't add scope. (Lesson from 2026-06-16/17.)
- **OpenClaw config (`~/.openclaw/openclaw.json`) is locked.** Read-only inspection OK, any write → ask first.
- **Caveman auto-clarity** — drop caveman for security warnings, destructive-action confirmations, multi-step sequences where fragment order risks misread. Resume after.

---

## Task management

Agents write to `tasks/DEVLOG.md` (newest at top) at the end of every session. Format and required fields are in `AGENTS.md`. This is mandatory — a missing DEVLOG entry breaks the next session's handoff.

Lessons from corrections go in `tasks/lessons.md` (newest at top, numbered L-0NN).

The full project spec lives at `tasks/kickoff-aureon-agent.md` — 14 sub-tasks across 5 phases. Read it after the 4 startup files, not before.
