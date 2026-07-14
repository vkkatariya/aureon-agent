# aureon-agent — Tasks

## Phase 0: Setup ✅
- [x] Workspace symlinks to ~/.openclaw/workspace/ (SOUL, USER, IDENTITY, WORKFLOW, MENTAL-MODEL, MEMORY, skills/, memory/)
- [x] AGENTS.md (6-rule per-project contract)
- [x] CONTEXT.md (stack, infra, decision log)
- [x] README.md (setup, env, run, workspace restore)
- [x] CLAUDE.md (Claude Code session context)
- [x] .gitignore (env, db, cache, openclaw scratch)
- [x] requirements.txt (httpx, python-telegram-bot, discord.py, aiosqlite, watchfiles, aiohttp, python-dotenv)
- [x] tasks/kickoff-aureon-agent.md (14 sub-tasks, 5 phases)
- [x] GitHub repo created (public)
- [x] CI pipeline active (Python 3.12, pip install -r requirements.txt, smoke tests)
- [x] dev branch created and pushed

## Phase 1: Workspace + doctrine (foundation) ✅
- [x] Sub-task 1: Workspace symlinks (all 11 wired to ~/.openclaw/workspace/)
- [x] Sub-task 2: Project bootstrap files (AGENTS.md, CONTEXT.md, AGENTS.md, README.md, .gitignore, requirements.txt)

## Phase 2: Core runtime (Tiny-OpenClaw ports) ✅
- [x] Sub-task 3: Memory + Session (SQLite) — aiosqlite, WAL mode, asyncio.Lock per session_id
- [x] Sub-task 4: Skill loader (OpenClaw format) — parses SKILL.md frontmatter (PyYAML); prose-only skills (all 8 current) get a synthesized `read_skill_<name>` tool; handler.py-based code skills (none yet) still supported; watchfiles hot-reload
- [x] Sub-task 5: Context builder (doctrine-aware) — SOUL + IDENTITY + skills menu + note:* + time, ~1.3K tokens measured
- [x] Sub-task 6: Agent runtime (Ollama + streaming + plan-node soft check) — ReAct loop, MAX_TOOL_ROUNDS=5, cloud fallback on connect/timeout errors, auto-clarity override for destructive patterns

## Phase 3: Channel adapters (multi-channel) ✅
- [x] Sub-task 7: Channel ABC + Router (router owns session bookkeeping + `/lesson` command; adapters own platform I/O)
- [x] Sub-task 8: Telegram adapter (python-telegram-bot, chat ID allowlist, streaming editMessageText throttled 1/sec, 4096-char chunking)
- [x] Sub-task 9: Discord adapter (discord.py, DM-only, streaming message.edit throttled 1/sec, 2000-char chunking)

## Phase 4: Entry + integration ✅
- [x] Sub-task 10: main.py (env load, wires Memory+Sessions+Skills+Agent+Router+channels, SIGINT/SIGTERM, optional 127.0.0.1 health endpoint)
- [x] Sub-task 11: Plan-node module (soft-warning helper, logs `plan_node_miss`, doesn't block)
- [x] Sub-task 12: Lessons writer (append to workspace/tasks/lessons.md, newest-first; wired to `/lesson <text>` in the router)

## Phase 5: Verification ✅
- [x] Sub-task 13: Smoke tests (`tests/smoke.py`) + agent loop e2e (`tests/test_agent_loop.py`) — both run and pass live against local Ollama (`minimax-m2.5:cloud` via the local proxy)
- [x] Sub-task 14: Dev workflow docs — README env vars updated (added `OLLAMA_CLOUD_BASE_URL`, corrected default model), DEVLOG entry pending commit

## Phase 6: Production hardening (post-MVP)
- [x] systemd user service at ~/.config/systemd/user/aureon-agent.service (PR #9 — unit template committed + install wired in setup.py, **live as PID 2372177 since 2026-07-13 22:43 CEST**, status: `active (running)`, `Restart=on-failure` survives crashes, `loginctl enable-linger` keeps it alive past logout)
- [x] PID lock at startup (PR #9 — `aureon_agent/pidlock.py`, prevents the Telegram 409 trap when two instances run on the same token)
- [x] Plan-node hard block (v2)
- [x] Subagent dispatch via the delegate_task pattern
- [x] Session compaction for long histories (PR pending, branch `feat/aureon-agent-session-compaction`)
  - [x] Sub-task 1: Token counting + model-aware threshold — `aureon_agent/models.py` (`MODEL_CONTEXT_WINDOWS`, unknown-model fallback 32K + WARN), `compaction/counter.py` (tiktoken `cl100k_base`, `len//4` fallback), `compaction/threshold.py` (`compute_compact_threshold`, `compute_recent_verbatim_size`, safety skip if system prompt >50% of context window)
  - [x] Sub-task 2: Summarization + audit log — `compaction/summarizer.py` (LLM-call summarizer, 300 max output tokens, 30s timeout, degraded-fallback-on-failure), `compaction/log.py` (`CompactionLog` append-only SQLite audit trail in `data/compaction_log.db`, never touches `sessions.db`)
  - [x] Sub-task 3: View-layer integration — `agent_runtime.py` `_maybe_compact()`/`_compact()` wired into `run()`, gated by `AUREON_COMPACTION_ENABLED` (default off), sliding-window + LLM-summary strategy, fail-open on any error
  - [x] Sub-task 4: Telemetry + doctor — `compactions_run_total`/`compactions_skipped_total` counters, `python -m aureon_agent compaction-log [--last|--session|--model]` CLI, `doctor.py` checks (`check_compaction_log`, `check_model_known`), CLAUDE.md Commands section updated
  - [x] Tests: `tests/test_compaction_counter.py`, `tests/test_compaction_threshold.py`, `tests/test_compaction_summarizer.py`, `tests/test_compaction_integration.py` (24 passed), live-verified against local Ollama (31320→3944 tokens, audit log recorded correctly)
  - [x] Live-channel test: 30+ Telegram messages on 32K model to observe auto-compaction firing; confirm no firing on 1M-context model (deferred — only verified via direct `_maybe_compact` calls, not a real channel round-trip)
- [x] **Phase 6.5 closeout (2026-07-13, this session):** Tier 1 + Tier 2 + Tier 3 (subagent) + Tier 4 (plan-node v2) all shipped to dev. Tier 4 was missing from dev when this session started — cherry-picked `f671a59` to dev at `ea06f46`. 13/13 pytest pass, doctor shows 7/8 green, plan-node v2 live-verified (3+ step blocks, read-only bypass, magic phrases work). 5 stale feature branches deleted. See `tasks/DEVLOG.md` closeout entry + `tasks/lessons.md` for 5 lessons learned.
- [ ] Webhook mode for Telegram (replace polling)
- [ ] Server/group channel support

## Phase 9: Cron Scheduler ✅

**Goal:** Add a background cron scheduler to the bot process that runs isolated agent turns on a schedule and delivers output to Telegram/Discord.

- [x] Sub-task 1: SQLite schema + db init (`aureon_agent/cron_db.py`) — `cron_jobs` + `cron_runs` tables, WAL mode, full CRUD
- [x] Sub-task 2: Schedule parsing (`aureon_agent/cron_schedule.py`) — cron/interval/at detection, croniter integration, top-of-hour staggering
- [x] Sub-task 3: CronScheduler core (`aureon_agent/cron.py`) — asyncio loop, job runner, delivery, rescheduling, overdue handling
- [x] Sub-task 4: SkillLoader subset (`skill_loader.py`) — `get_tools_subset(names)` for per-job skill loading
- [x] Sub-task 5: CLI subcommands (`aureon_agent/cron_cli.py`) — list, create, pause, resume, run, remove, runs, status
- [x] Sub-task 6: Integration + tests + docs
  - [x] Wired into `aureon_agent/cli.py` (starts after channels, stops before teardown)
  - [x] Wired into `aureon_agent/__main__.py` (cron subcommand group)
  - [x] Doctor health check (`check_cron_scheduler` in `aureon_agent/doctor.py`)
  - [x] `croniter>=1.4` added to `requirements.txt`
  - [x] Tests: 24 tests in `tests/test_cron.py` (all passing)
  - [x] Docs: `docs/cron.md` (schedule types, CLI, delivery, heartbeat comparison, troubleshooting)
  - [x] 37/37 total tests pass (13 existing + 24 new)
  - [x] Live test via Telegram: `homelab-health-daily` cron job created (`0 8 * * *`, skill `homelab-health`, deliver telegram), matches Hermes job `bcfd979f8bd0`

## Phase 9.5: Cron tools + TUI banner + bug fixes (2026-07-14/15, this session)

**Goal:** Add cron tools to the agent's tool registry (so Captain can create/list/remove cron jobs via Telegram chat), replace the TUI banner with a pixel-art version matching the README SVG, and fix 3 bugs that were causing "(no response)" on Telegram.

**Cron tools (commit `062702f`):**
- [x] `cron_create` tool — LLM can create cron jobs from Telegram chat (schedule + name + prompt + optional skills/deliver/repeat)
- [x] `cron_list` tool — LLM can list all cron jobs
- [x] `cron_remove` tool — LLM can delete a job by ID
- [x] `cron_pause` tool — LLM can pause a job
- [x] `cron_resume` tool — LLM can resume a paused job
- [x] All 5 tools call the same `cron_db.py` + `cron_schedule.py` as the CLI (no duplication)

**TUI banner (commit `fcc49d0`):**
- [x] Replaced simple `🦾 Aureon Agent Setup` Panel with pixel-art `AUREON-AGENT` wordmark
- [x] 5x7 pixel font (same as `scripts/generate_banner.py`)
- [x] Warm orange gradient: `#FFD24A` → `#FF8A2B` → `#E85D04` (matching `assets/banner.svg`)
- [x] Top + bottom accent bars in `#E85D04`
- [x] Version tagline + GitHub URL at bottom
- [x] Shows in: `aureon-agent-doctor`, `aureon-agent setup`, `aureon-agent postinstall`

**Bug fixes (commits `1015753`, `c42d136`, `3894977`, `503f2ce`):**
- [x] `telegram.py:84-95` — fall back to streamed text when LLM returns empty final response (L-084)
- [x] `terminal.py` — accept string commands (not just lists), parse with `shlex.split()` (L-086: LLM naturally sends strings, not arrays)
- [x] `agent_runtime.py` — JSON schema for terminal tool now uses `oneOf: [array, string]`
- [x] `terminal.py` — expand `~` in path-like arguments (`subprocess.run` with `shell=False` doesn't expand `~`)
- [x] `agent_runtime.py` — force final summary call after `MAX_TOOL_ROUNDS=5` with no text (LLM was looping tool calls, never producing text)
- [x] `agent_runtime.py` — fix cron tools DB path: single `dirname(__file__)` not double (agent_runtime.py is at project root, not inside `aureon_agent/`)

**Acceptance criteria:**
- [x] Captain can say "create a daily health check cron at 8am" on Telegram → bot calls `cron_create`
- [x] Captain can say "list my cron jobs" → bot calls `cron_list`, returns real jobs
- [x] TUI banner matches README SVG style (pixel-art, orange gradient, accent bars)
- [x] Bot responds to all messages (no more "(no response from LLM)")
- [x] `terminal` tool works with both string and array commands
- [x] `~` paths expand correctly in terminal commands
- [x] Long tool-call chains (5+ rounds) end with a forced summary response
- [x] 37/37 tests pass
- [x] Bot live under systemd, Telegram round-trip verified


## Phase 6.5: Tier 1 + Tier 2 tools (Hermes parity)

**Goal:** Add the 5 high-leverage tools the agent is missing compared to Hermes's 23 built-in toolsets. Pairs with the plan-node hard block — the agent can now maintain its own plan and ask clarifying questions before doing destructive work.

**Tier 1 (PR #14 kickoff merged, code shipped via agent on `feat/aureon-agent-tier1-tools` then merged into dev):**
- [x] Sub-task 1: `WorkspaceBoundTool` base class + `confirm_with_captain()` helper + `ToolLog` audit (in `data/tool_log.db`) — `aureon_agent/tools/{base,confirm,log}.py`
- [x] Sub-task 2: `terminal` tool — shell access with allowlist + Captain confirmation for destructive ops, 30s timeout, no `shell=True` (prevents injection)
- [x] Sub-task 3: `file` tool — 3 sub-tools (`read_file`/`write_file`/`list_dir`) with workspace allowlist (`~/dev-shared/projects/` rw, `~/.openclaw/workspace/` ro), binary writes rejected, UTF-8 only
- [x] Sub-task 4: `web` tool — `web_search` (DuckDuckGo HTML, no API key) + `web_fetch` (httpx GET, 10s/30s timeouts, robots.txt respected)
- [x] Sub-task 5: Tool registry integration in `agent_runtime.py` — register all 3, route by name in dispatch
- [x] Sub-task 6: Telemetry + doctor + docs — `aureon-agent tool-log --last 10` CLI, `doctor` checks workspace allowlist, `docs/tools.md`

**Tier 2 (PR #15 kickoff merged, code shipped via agent on `feat/aureon-agent-tier2-tools` then merged into dev):**
- [x] Sub-task 1: `todo` tool — 3 sub-tools (`todo_read`/`todo_write`/`todo_add`) for `tasks/todo.md`, workspace allowlist, Markdown format
- [x] Sub-task 2: `clarify` tool — pause ReAct loop via `asyncio.Future` + per-session `pending_clarifications` registry in `channels/router.py`, 1-per-iteration + 3-per-session caps, 5min default timeout
- [x] Sub-task 3: Tool registry integration in `agent_runtime.py` — register both, route by name
- [x] Sub-task 4: Telemetry + doctor + docs — `aureon-agent clarify-log --last 10` CLI, doctor checks

**Subagent dispatch (Tier 3, shipped via agent on `feat/aureon-agent-subagent-dispatch` then merged into dev):**
- [x] `aureon_agent/subagent/{base,task,result,claude_code,sandbox,log,tool}.py` — `SubagentBackend` ABC, `ClaudeCodeBackend` shells to `claude -p`, sandbox via `shutil.copytree` to `/tmp/aureon-subagent-<uuid8>/`
- [x] `delegate_task` tool — synthesized, cost-control (refuse >50K tokens), 5min timeout, JSON output with summary + diff
- [x] `data/subagent_log.db` audit log (append-only SQLite)
- [x] `aureon-agent subagent-log --last 10` CLI
- [x] `check_claude_cli()` health check (fixed missing `import shutil` in doctor.py)

**Plan-node hard block v2 (Tier 4, shipped via agent on `feat/aureon-agent-plan-node-hard-block` then merged into dev):**
- [x] `plan_node.py` — heuristic feature counter (imperative verbs, conjunctions, URLs, file paths). 3+ → block.
- [x] `agent_runtime.py` — hard block before first ReAct iteration, fails open
- [x] Read-only bypass (`show`, `list`, `display`, `what is`, `how many`)
- [x] Bypass phrases (`just do it`, `skip the plan`, `simple task`) — accepted with WARN log
- [x] `has_plan` checks both `tasks/todo.md` and `~/.openclaw/workspace/tasks/todo.md`
- [x] `tests/test_plan_node.py` — 2 tests covering count_features + require_plan
- [x] `check_plan_node()` health check in doctor

**Acceptance criteria (all 4 work items, verified on merged dev at `740f208`):**
- [x] `WorkspaceBoundTool.validate_path` enforces `~/dev-shared/projects/` (rw) + `~/.openclaw/workspace/` (ro)
- [x] `terminal` tool: allowlisted commands run, destructive ask
- [x] `file` tool: 3 sub-tools, binary rejected, workspace allowlist
- [x] `web` tool: search + fetch work
- [x] `todo` tool: 3 sub-tools work, workspace allowlist
- [x] `clarify` tool: pauses ReAct loop, waits for Captain, resumes
- [x] `delegate_task` tool: shells out to claude-code, sandbox, audit, cost control
- [x] `plan_node` hard block: 3+ steps → block, 1-2 proceed, read-only bypass, magic phrases
- [x] All tools log to `data/tool_log.db` + `data/subagent_log.db`
- [x] `aureon-agent tool-log` + `clarify-log` + `subagent-log` + `compaction-log` all work
- [x] `aureon-agent doctor` checks Tools Allowlist, Claude CLI, Plan Node, Model Registry
- [x] 13/13 pytest tests pass (config, doctor, plan_node, subagent, tier2_tools, tools)
- [x] `python tests/smoke.py` passes
- [x] Live-Telegram tests deferred (manual, requires real chat context)

**Out of scope (v1):** browser/computer_use, image_gen/video_gen, spotify/homeassistant/yuanbao, per-command timeout overrides, background processes, real-time streaming output, subagent `todo`, rich `clarify` UIs, multi-party clarifications, persistent clarification state, `todo` history/archive

## Phase 7: MCP integration (keep local skills, add MCP for new services)

**Decision (2026-07-13, Captain's call):** **Keep both registries.** Local doctrine skills (SKILL.md + handler.py) stay forever. MCP servers are **additive** for new services only. Agent Runtime merges both tool lists at boot. Gradual migration, zero rewrite of working code.

**Why hybrid, not full migration:**
- Doctrine skills (caveman, homelab-*, project-init, nano-banana-pro, notion, openclaw-health) already work, audited, doctrine-aware.
- MCP server dependency surface is large — new code to vet per service.
- Two registries is fine until 5+ MCP servers, then reconsider.

**Architecture:**
```
[ Telegram ] [ Discord ]
        \       /
   [ Channel Router ]
              |
   [ Agent Runtime ] ← ReAct loop, MAX_TOOL_ROUNDS=5, Ollama streaming
              |
   [ Tool Registry ] ← merged tool list
       /         \
      /           \
[Skill Loader]   [MCP Client]
  (8 doctrine      (N MCP servers
   skills)          on demand)
```

Both backends expose tools to the LLM in the same tool-use format. LLM doesn't know or care which backend served the tool.

**Sub-task 15: MCP client + tool registry merger (Phase 7.1)**
- [ ] `mcp_client.py` — connection manager (stdio + HTTP/SSE), graceful failure per server
- [ ] `tool_registry.py` — merge `skill_loader.get_tools()` + `mcp_client.list_tools()` into one flat list
- [ ] Add `mcp` to `requirements.txt`
- [ ] Update `agent_runtime.py` to route tool calls to right backend (skill_loader.execute_tool vs mcp_client.call_tool)
- [ ] Test: 1 doctrine skill + 1 MCP server both load, both invokable, no double-registration

**Sub-task 16: First MCP server — Notion (Phase 7.2)**
- [ ] Decide: replace existing `notion` skill (full migration) OR run both (parallel)
- [ ] Recommend: **keep notion skill as fallback, add Notion MCP server as primary** — easy rollback
- [ ] Use official `mcp-server-notion` if available, else community `@gongrzhe/notion-mcp-server`
- [ ] Pass `NOTION_TOKEN` via subprocess env
- [ ] Test: list pages, create page, query database — all via MCP

**Sub-task 17: Gmail MCP server (Phase 7.3)**
- [ ] `gmail-mcp-server` (community) or roll our own
- [ ] OAuth dance: credentials in `~/.openclaw/.env` (chmod 600), refresh token handled by server
- [ ] Deploy as **HTTP/SSE on athena** (Tailscale-only, port 127.0.0.1:N) — shared across agents
- [ ] aureon-agent connects via HTTP, not stdio
- [ ] Test: list inbox, search, send (with explicit confirmation per channel-policy-spec)

**Sub-task 18: GitHub MCP server (Phase 7.4)**
- [ ] Official `@modelcontextprotocol/server-github` via stdio
- [ ] Token in env: `GITHUB_TOKEN` (read-only scope for v1)
- [ ] Use cases: list PRs, read issues, comment on issues (with confirmation)
- [ ] No write operations until Captain explicitly enables

**Sub-task 19: Filesystem MCP server (Phase 7.5)**
- [ ] Official `@modelcontextprotocol/server-filesystem`
- [ ] Sandbox to `~/dev-shared/projects/` only — never `/home/radxa` or `/etc` or `/`
- [ ] Safer than the LLM having raw `bash` access via the homelab skill

**Sub-task 20: Homelab MCP server (Phase 7.6, roll our own)**
- [ ] Wrap existing `homelab-deploy` / `homelab-health` skills as MCP server
- [ ] stdio, one process per agent
- [ ] Lets us retire the skill format for homelab if MCP proves cleaner

**Auth model (per service):**
- **stdio servers:** secrets via subprocess `env=` param. Never touch network between agent and server.
- **HTTP/SSE servers:** secrets live in server process, not agent. Agent just needs URL.
- **Single source of truth:** `~/.openclaw/.env` (chmod 600), env-var refs. Per Captain's config lock rule — `openclaw.json` write = ask first.

**Failure handling:**
- MCP server dies at boot → log warning, continue with what loaded (skills-only mode)
- MCP server dies mid-session → tool call returns `{"error": "server unreachable"}`, agent retries once, then surfaces to user
- No silent failure. Captain's rule.

**Migration decision matrix (v2+):**
- 1-2 MCP servers: keep both registries, document the split
- 3-5 MCP servers: consider a thin "tool router" wrapper that hides the split
- 5+ MCP servers: **full migration** to MCP, retire skill format. Only do this when 8+ services exist and the migration cost is justified.

**Phase 7 Acceptance criteria**

- [x] Agent blocks 3+ step tasks without a plan, with clear Telegram/Discord message
- [x] Agent proceeds when plan exists
- [x] Agent proceeds when bypass phrase used, with WARN log
- [x] Read-only requests never trigger
- [x] Step counter catches: 3+ imperative verbs, 3+ file paths, 3+ URLs
- [x] Plan file read errors fail open
- [x] Doctor passes
- [x] pytest passes (8+ tests)
- [x] Live test: 3-step task blocks, bypass phrase works, plan file works

**Sub-task 1: Foundation** ✅ (PR #8)
- [x] Add `rich` + `questionary` to `requirements.txt`
- [x] Create `aureon_agent/` package: `__init__.py`, `__main__.py`, `cli.py`, `setup.py`, `doctor.py`, `postinstall.py`, `config.py`, `tui.py`
- [x] Move `main.py` → `aureon_agent/cli.py`, back-compat shim keeps `python main.py` working
- [x] Add `pyproject.toml` with console script entries
- [x] Verify `pip install -e .` + all console scripts work

**Sub-task 2: Config layer** ✅ (PR #8)
- [x] `aureon_agent/config.py` — `@dataclass AureonConfig` with all settings, `from_env()`, `from_file()`, `save(path)`, `validate()`, `redact()`, `is_complete()`
- [x] `aureon_agent/tui.py` — Rich/Questionary helpers: `print_banner`, `confirm`, `select`, `checkbox`, `text`, `password`, `path`, `print_status`, `print_table`, `spinner`, `progress`
- [x] `tests/test_config.py` — round-trip, redaction, validation, missing fields
- [x] `tests/test_setup.py` — mocked TUI flow

**Sub-task 3: Wizard steps (5-8 from kickoff)** ✅ (PR #8)
- [x] Step 1: existing config detection (Keep | Modify | Reset via `trash`)
- [x] Step 2: model + LLM provider (Ollama local/cloud, API key, model selection, optional connection test)
- [x] Step 3: Telegram channel (token, `getMe` validation, allowlist, optional `getUpdates` chat_id extraction, optional handshake)
- [x] Step 4: Discord (optional, skip per Captain) + health port + log level + skills list + systemd daemon install
- [x] systemd unit template (generated by wizard at install, not committed as source)
- [x] `loginctl enable-linger $USER` check (warn if not enabled, per systemd convention)

**Sub-task 4: Doctor + postinstall + top-level glue (9-12 from kickoff)** ✅ (PR #8, with 1 follow-up)
- [x] `aureon_agent/doctor.py` — Python version, venv, .env perms, workspace symlinks, Ollama probe, Telegram probe, systemd status, runs `tests/smoke.py`. Rich table output. Exit 0/1/2.
- [x] `aureon_agent/postinstall.py` — Python version check, venv create, pip install, Ollama check (offer install instructions, don't actually install system packages)
- [x] `aureon_agent/__main__.py` — subcommand parser: `setup | postinstall | doctor | start | stop | status | logs | version | help`
- [x] `start` = run bot in foreground; `stop`/`status`/`logs` = systemd wrapper; `version` = print version
- [x] Update `README.md` with new command surface + setup-script behavior section
- [x] Add `docs/setup-script.md` matching the wizard.md structure (sections, modes, examples)
- [x] Update `CLAUDE.md` Commands section to reference new top-level commands

**Acceptance criteria:** ✅ (PR #8)
- [x] `aureon-agent setup` walks a new Captain through first install end-to-end
- [x] `aureon-agent setup --non-interactive` works without TTY
- [x] `aureon-agent setup --quick` only prompts for unset fields
- [x] `aureon-agent setup --reset` confirms destructive action, uses `trash` not `rm`
- [x] `aureon-agent doctor` exits 0 on healthy live system
- [ ] systemd service live, survives `systemctl --user restart`, `aureon-agent logs` shows Telegram polling (deferred — not in v1)
- [x] Existing Telegram round-trip still works after the refactor
- [x] All new/modified tests pass: `tests/test_config.py`, `tests/test_setup.py`, `tests/test_doctor.py`, `tests/smoke.py`, `tests/test_agent_loop.py`
- [x] README updated, `docs/setup-script.md` matches wizard.md structure
- [x] PR opened to `dev`, DEVLOG entry written

**Out of scope (v1):** non-Linux daemon, i18n, SecretRef/external vault, OAuth flows, multi-agent routing, web search picker, auto-update, TUI mouse support, workspace reset (would nuke Captain's state via symlink).

**Full spec:** `tasks/kickoff-setup-script.md` (18KB, 12 sub-tasks detailed)

**References:**
- OpenClaw docs: `~/.npm-global/lib/node_modules/openclaw/docs/start/{wizard,wizard-cli-reference,wizard-cli-automation,setup}.md`
- OpenClaw health check: `~/.openclaw/workspace/scripts/openclaw-health.sh`
- [ ] Sub-task 4: TUI helpers
- [ ] Sub-task 5: Step 1 — Existing config detection
- [ ] Sub-task 6: Step 2 — Model + LLM provider
- [ ] Sub-task 7: Step 3 — Telegram channel
- [ ] Sub-task 8: Step 4 — Discord channel + health + daemon + skills
- [ ] Sub-task 9: Doctor command
- [ ] Sub-task 10: Postinstall command
- [ ] Sub-task 11: Top-level CLI glue
- [ ] Sub-task 12: README + docs
