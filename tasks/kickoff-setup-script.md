# Task: Build interactive setup script for aureon-agent

**Branch:** `feat/aureon-agent-setup-script` (off `dev`)
**Mode:** Builder
**Complexity:** Non-trivial — interactive CLI + non-interactive mode + postinstall + systemd integration
**Estimated effort:** 1–2 evenings, ~400-600 LoC

---

## Setup

- **Project:** `aureon-agent`
- **Path on athena:** `~/dev-shared/projects/aureon-agent/`
- **Working directory:** this repo
- **Active branch:** `feat/aureon-agent-setup-script` (off `dev`)
- **Session name:** `[aureon-agent]-local` (you're the local session, persistent tmux)

## What this is

An interactive setup script for aureon-agent that mirrors the OpenClaw `onboard` + Hermes `setup` patterns, adapted to a single-process Python agent on Linux. Lets a new Captain install + configure + start the agent end-to-end in one command. No prior knowledge of `.env` files, virtualenvs, or systemd required.

**Reference docs (read before designing):**

- **OpenClaw `onboard`:** `~/.npm-global/lib/node_modules/openclaw/docs/start/wizard.md` + `wizard-cli-reference.md` + `wizard-cli-automation.md` + `cli/onboard.md`
- **OpenClaw `setup` (advanced):** `~/.npm-global/lib/node_modules/openclaw/docs/start/setup.md`
- **Hermes `setup`:** `hermes setup --help` (already installed locally)
- **Hermes `postinstall`:** `hermes postinstall --help` (already installed locally)
- **Existing OpenClaw health check pattern:** `~/.openclaw/workspace/scripts/openclaw-health.sh`
- **Existing aureon-agent:** `main.py`, `.env`, `data/`, `tests/smoke.py`, `tests/test_agent_loop.py`

## Decisions confirmed with user (2026-07-13)

- **Stack:** Python 3.12 + `rich` (TUI) + `questionary` (prompts) + standard library for the rest
- **Entry point:** `python -m aureon_agent.setup` AND `aureon-agent-setup` console script (added to `pyproject.toml`/`setup.py`)
- **Modes:** Interactive (default) | `--quick` (only missing/unset) | `--non-interactive` (use defaults/env) | `--reset` (wipe config)
- **Sections** (match Hermes): `model | channel | daemon | skills | workspace | all`
- **Channels:** Telegram (primary, already validated) + Discord (optional, skip per Captain)
- **Daemon:** systemd user unit on Linux only (no macOS LaunchAgent, no Windows Scheduled Task — Captain runs on Linux per OpenClaw `~/.openclaw/workspace/MEMORY.md`)
- **Health check:** reuse existing `tests/smoke.py` (skill load, DB roundtrip, context builder, agent loop), wire as `aureon-agent doctor`
- **Locale:** English only (Captain's working language per `~/.openclaw/workspace/USER.md`). No i18n for v1.
- **Secret storage:** plaintext in `.env` (chmod 600) for v1. SecretRef/external-vault deferred to v2.
- **No "Reset workspace" option** — the workspace is symlinked to `~/.openclaw/workspace/`, destroying it nukes Captain's OpenClaw state. v1 is `Reset config only`.

## Read these on session start (in order)

1. `CLAUDE.md` — project context
2. `CONTEXT.md` — stack, infra, decisions
3. `tasks/DEVLOG.md` (last 3 entries) — current world state
4. `tasks/todo.md` — Phase 6 status
5. `tasks/kickoff-aureon-agent.md` — full project spec (read after the 4 above)
6. This file (the kickoff)
7. `~/.openclaw/workspace/MEMORY.md` §Olympus (already symlinked into `workspace/`) — agent routing, channel-policy
8. `references/tiny-openclaw/README.md` — for context on Tiny-OpenClaw's CLI-less design (we add the CLI here, since OpenClaw pattern expects one)

## Your role

You are building an interactive CLI. Use `questionary` for prompts (radii, checkboxes, password inputs), `rich` for the TUI (panels, tables, spinners, progress bars). The 6-rule per-project contract from `AGENTS.md` applies:
1. Plan first → `tasks/todo.md` checkable items
2. Subagent for parallel research if needed (probably not — this is mostly mechanical)
3. Self-improvement loop → `workspace/tasks/lessons.md` on correction
4. Verify before done — `aureon-agent doctor` must pass after the script runs
5. Demand elegance — for non-trivial design choices, propose a simpler way
6. Autonomous bug fixing — given a setup error, fix it

---

## 8 sub-tasks (in order)

### Phase A: Foundation

**Sub-task 1: Add CLI deps + console script entry (15 min)**
- Add to `requirements.txt`: `rich>=13`, `questionary>=2`
- Add to `pyproject.toml` (or `setup.py` — check if exists, create if not) a `[project.scripts]` entry: `aureon-agent-setup = aureon_agent.setup:main`
- Same for `aureon-agent-doctor = aureon_agent.doctor:main`
- Same for `aureon-agent = aureon_agent.cli:main` (the actual run-bot command, replacing `python main.py`)
- Verify: `pip install -e .` works, `aureon-agent-setup --help` shows

**Sub-task 2: Module skeleton (20 min)**
Create `aureon_agent/` package directory:
- `aureon_agent/__init__.py` — version string
- `aureon_agent/__main__.py` — `python -m aureon_agent` entry
- `aureon_agent/cli.py` — `main.py` moves here as `cli.py` (re-export from `__init__.py` for back-compat with `python main.py`)
- `aureon_agent/setup.py` — the setup wizard (this sub-task creates the skeleton only)
- `aureon_agent/doctor.py` — the health check command
- `aureon_agent/config.py` — load/save `.env`, validate, expose typed dataclass
- Move `main.py` → `aureon_agent/cli.py`, update import paths in tests
- Verify: `aureon-agent --help` and `aureon-agent-setup --help` both work, existing tests still pass

### Phase B: Config layer

**Sub-task 3: Typed config dataclass (45 min)**
- `aureon_agent/config.py`:
  - `@dataclass AureonConfig` with all settings as fields (OLLAMA_BASE_URL, OLLAMA_API_KEY, OLLAMA_MODEL, TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_CHATS, DISCORD_BOT_TOKEN, HEALTH_PORT, LOG_LEVEL)
  - `@classmethod from_env()` — reads env via `python-dotenv`, returns config
  - `@classmethod from_file(path)` — reads `.env` directly via `dotenv_values`
  - `def save(self, path)` — writes to `.env` with `chmod 600`
  - `def validate(self)` — checks required fields, returns list of errors
  - `def redact(self)` — returns a copy with secrets redacted (for logging)
  - `def is_complete(self)` — returns True if all required fields are set
- `def get_chat_id_from_update(token)` — helper to extract chat_id from a `getUpdates` response
- Tests: `tests/test_config.py` — round-trip, redaction, validation, missing fields

**Sub-task 4: TUI helpers (30 min)**
- `aureon_agent/tui.py`:
  - `print_banner()` — Rich panel with agent name, version, "Welcome to aureon-agent setup"
  - `print_section(title, body)` — Rich section header
  - `confirm(prompt, default=False)` — yes/no via questionary
  - `select(prompt, choices, default=None)` — radio list
  - `checkbox(prompt, choices, default=[])` — multi-select
  - `text(prompt, default="", validate=None, password=False)` — text input
  - `password(prompt, validate=None)` — masked text input (for tokens)
  - `path(prompt, default="", must_exist=False)` — path input
  - `print_status(message, status)` — success/error/warn with icon
  - `print_table(headers, rows, title=None)` — Rich table
  - `spinner(message)` — context manager that shows a spinner while work runs
  - `progress(message)` — context manager for indeterminate progress

### Phase C: Setup wizard steps

**Sub-task 5: Step 1 — Existing config detection (20 min)**
- On wizard start, check if `.env` exists
- If yes + non-interactive: print current values, exit (OpenClaw pattern)
- If yes + interactive: ask Keep | Modify | Reset
  - Keep: load current values, skip to step 2 with defaults pre-filled
  - Modify: same as fresh, but pre-fill with current values (Hermes `--reconfigure` pattern)
  - Reset: confirm destructive action, `trash` the file, proceed as fresh
- If no: proceed as fresh install

**Sub-task 6: Step 2 — Model + LLM provider (45 min)**
- Prompt for `OLLAMA_BASE_URL` (default: `http://127.0.0.1:11434/v1`)
- Prompt for `OLLAMA_API_KEY` (password, optional for local)
- Prompt for `OLLAMA_MODEL` (default: `minimax-m2.5:cloud` for local, `minimax-m3` for cloud)
- If `OLLAMA_BASE_URL` is `https://ollama.com/v1`, require `OLLAMA_API_KEY` (validate)
- Optional: test the connection (POST `/v1/models` or `/v1/chat/completions` with a tiny prompt)
- If test fails, warn but allow save (Captain might want to defer testing)

**Sub-task 7: Step 3 — Telegram channel (30 min)**
- Prompt for `TELEGRAM_BOT_TOKEN` (password, required if Telegram enabled)
- If provided: call `getMe` to validate, show bot username
- Prompt for `TELEGRAM_ALLOWED_CHATS` (comma-separated chat IDs)
- If empty, warn "all messages will be dropped"
- Optional: call `getUpdates` to extract a chat_id from a recent `/start` message, offer to add to allowlist
- Optional: send a handshake message to confirm round-trip

**Sub-task 8: Step 4 — Discord channel + health + daemon + skills (45 min)**
- Discord: prompt for token (optional, can skip per Captain's decision)
- Health: prompt for `HEALTH_PORT` (default: 7777, blank = disabled)
- Log level: select from DEBUG/INFO/WARNING/ERROR
- Skills: list available skills in `workspace/skills/`, show counts (no install needed — they auto-load)
- Daemon: ask "Install systemd user service?" (default: yes)
  - If yes: generate `~/.config/systemd/user/aureon-agent.service`, run `systemctl --user daemon-reload && systemctl --user enable aureon-agent.service && systemctl --user start aureon-agent.service`
  - Show status: `systemctl --user status aureon-agent.service --no-pager`
  - Show "tail logs" command: `journalctl --user -u aureon-agent.service -f`

### Phase D: Verify + ship

**Sub-task 9: Doctor command (30 min)**
- `aureon_agent/doctor.py`:
  - Check Python version ≥ 3.12
  - Check venv exists + has all requirements installed
  - Check `.env` exists + is `chmod 600` + has required fields
  - Check `workspace/` symlinks resolve (SOUL.md, IDENTITY.md, MEMORY.md, skills/, memory/)
  - Check Ollama reachable (POST to OLLAMA_BASE_URL)
  - Check Telegram bot reachable (call `getMe` if token set)
  - Check systemd service status if installed (`systemctl --user is-active aureon-agent.service`)
  - Run `tests/smoke.py` (skill load, DB roundtrip, context builder, agent loop)
  - Print Rich table: check name | status (✅/❌/🟡) | details
  - Exit code: 0 = all green, 1 = any red, 2 = missing config
- Wire as `aureon-agent doctor` console script
- Also expose as `aureon-agent-setup doctor` (alias)

**Sub-task 10: Postinstall command (20 min)**
- `aureon_agent/postinstall.py`:
  - Check `python3.12` available (offer to install via `apt` or `uv` if missing — just print guidance, don't actually install system packages)
  - Check `pip` available
  - Check Ollama running (offer install instructions: `curl -fsSL https://ollama.com/install.sh | sh`)
  - Check `~/.local/bin` in PATH
  - Create `.venv` if missing (`python3.12 -m venv .venv`)
  - Install requirements (`pip install -r requirements.txt`)
  - Wire as `aureon-agent postinstall` console script
  - Reuse pattern from Hermes `postinstall` (bootstraps non-Python deps)

**Sub-task 11: Top-level CLI glue (15 min)**
- `aureon_agent/__main__.py`:
  - Subcommand parser: `aureon-agent {setup,postinstall,doctor,start,stop,status,logs,version,help}`
  - `start` = run the bot in foreground (current `main.py` behavior, but with proper signal handling)
  - `stop` = `systemctl --user stop aureon-agent.service`
  - `status` = `systemctl --user status aureon-agent.service --no-pager`
  - `logs` = `journalctl --user -u aureon-agent.service -f`
  - `version` = print version
  - Default subcommand: `start` (so `aureon-agent` just works)

**Sub-task 12: README + docs (20 min)**
- Update `README.md` with the new commands:
  - First install: `git clone ... && cd aureon-agent && python3.12 -m venv .venv && source .venv/bin/activate && pip install -e . && aureon-agent postinstall && aureon-agent setup`
  - Reconfigure: `aureon-agent setup --section channel`
  - Reset: `aureon-agent setup --reset`
  - Non-interactive: `aureon-agent setup --non-interactive --telegram-bot-token "$TG" --telegram-allowed-chats 723865496`
  - Check health: `aureon-agent doctor`
  - Start: `aureon-agent start` or `aureon-agent` (default)
  - Stop: `aureon-agent stop`
  - Logs: `aureon-agent logs`
- Add a "Setup script behavior" section explaining modes (interactive/quick/non-interactive) like OpenClaw's `wizard.md`
- Update `CLAUDE.md` Commands section to reference the new top-level commands

---

## File layout (target)

```
aureon-agent/
├── aureon_agent/                       # NEW: package
│   ├── __init__.py                     # version
│   ├── __main__.py                     # entry: aureon-agent {setup|start|...}
│   ├── cli.py                          # run-bot command (moved from main.py)
│   ├── setup.py                        # setup wizard (this work)
│   ├── doctor.py                       # health check
│   ├── postinstall.py                  # dep bootstrap
│   ├── config.py                       # typed config + .env IO
│   └── tui.py                          # rich/questionary helpers
├── main.py                             # back-compat shim: imports aureon_agent.cli
├── pyproject.toml                      # NEW: package metadata + console scripts
├── systemd/
│   └── aureon-agent.service            # NEW: systemd user unit template
├── tests/
│   ├── test_config.py                  # NEW
│   ├── test_setup.py                   # NEW (mocked TUI)
│   ├── test_doctor.py                  # NEW
│   ├── smoke.py                        # unchanged
│   └── test_agent_loop.py              # unchanged
├── .env                                # gitignored
└── docs/
    └── setup-script.md                 # NEW: design doc (matches OpenClaw wizard.md)
```

## systemd user unit template

```ini
# ~/.config/systemd/user/aureon-agent.service
[Unit]
Description=aureon-agent (Telegram + Discord personal AI agent)
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/radxa/dev-shared/projects/aureon-agent
ExecStart=/home/radxa/dev-shared/projects/aureon-agent/.venv/bin/python -m aureon_agent
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

## Truthfulness guardrails (per OpenClaw SOUL.md + lessons)

- Ground every claim in tested behavior. No "should work" hand-waving.
- Disallow defensive or apologetic language unless a real mistake was made.
- Apply "scope discipline" lesson from `~/.openclaw/workspace/MEMORY.md` §"🦾 Lessons from 2026-06-16/17": write what was asked, stop, don't add scope
- Captain's command: "**Telegram chat ID allowlist**" — `aureon-agent doctor` MUST check allowlist is non-empty if Telegram is enabled
- Captain's rule: "**No `0.0.0.0` binds**" — `HEALTH_PORT` binds to `127.0.0.1` only, no exception

## Quality gates

- `aureon-agent setup --help` shows all options
- `aureon-agent setup --non-interactive` works without TTY (no questionary prompts)
- `aureon-agent setup --quick` only prompts for unset fields
- `aureon-agent setup --reset` confirms destructive action, uses `trash` not `rm`
- `aureon-agent doctor` exits 0 when healthy, 1 when any check fails
- `aureon-agent postinstall` creates venv + installs deps idempotently
- All new console scripts work: `aureon-agent`, `aureon-agent-setup`, `aureon-agent-doctor`, `aureon-agent-postinstall`
- Existing tests still pass: `python tests/smoke.py`, `python tests/test_agent_loop.py`
- systemd service starts, status shows "active (running)", `journalctl` shows live logs
- Bot survives `systemctl --user restart aureon-agent.service`
- Locale-aware: hardcode "en" for v1, structure code so i18n can be added later (per OpenClaw pattern)

## Definition of Done

- [ ] All 12 sub-tasks complete
- [ ] `aureon-agent setup` walks a new Captain through first install end-to-end
- [ ] `aureon-agent doctor` reports clean on the live system (after running setup)
- [ ] systemd service live, survives restart, `aureon-agent logs` shows Telegram polling
- [ ] Existing Telegram round-trip still works after the refactor (bot responds to DMs)
- [ ] All 5 new/modified tests pass
- [ ] README updated with new command surface
- [ ] `docs/setup-script.md` matches OpenClaw's `wizard.md` structure (sections, modes, examples)
- [ ] Branch committed + pushed, PR opened to `dev`
- [ ] DEVLOG entry written

## Mode + Complexity

- **Mode:** Builder (CLI design + implementation)
- **Complexity:** Non-trivial full workflow (per `workspace/MENTAL-MODEL-TEMPLATE.md` §2)
- **One-shot or incremental:** Sub-tasks 1-2 first (foundation), 3-4 (config + TUI), 5-8 (wizard steps), 9-12 (verify + ship). Each phase is testable independently.

## Branch strategy (per OpenClaw git contract)

- `main` — stable, deployable baseline
- `dev` — integration branch
- `feat/aureon-agent-setup-script` — this work, branched off `dev`
- Commits: `feat(aureon-agent):` or `fix(aureon-agent):` or `docs(aureon-agent):`
- One task = one branch. Push before session ends. PR against `dev`.

## On completion

- Notify Captain via Telegram (the existing bot)
- Append DEVLOG entry
- Wait for sign-off before merging to `dev`
- Run `aureon-agent doctor` one final time, paste output in PR description

## Out of scope (v1)

- Non-Linux daemon (LaunchAgent, Scheduled Task) — Captain runs Linux only
- i18n / locale support beyond "en"
- SecretRef / external vault (Bitwarden, 1Password) — plaintext .env only
- OAuth flows (Anthropic, OpenAI) — not needed for Ollama + bot tokens
- Multi-agent routing (`agents add work`, `agents bind`, etc.) — single agent only
- Web search step in wizard (OpenClaw includes Brave/DDG/Perplexity picker) — not needed
- Auto-update / OTA check
- TUI mouse support (keyboard only)
- Multi-language prompts (en/zh-CN/zh-TW)
- Workspace reset (destructive + symlinked to OpenClaw state — would nuke Captain's identity)
