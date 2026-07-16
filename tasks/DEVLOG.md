# Dev Log
> Append-only. Agents write an entry at the end of every session. Newest at top.

---

## 2026-07-16 — Phase 7.1: MCP foundation + Notion PoC (branch `feat/aureon-agent-phase7-mcp`)
**Did:** Built the MCP integration foundation: MCP client module, unified tool registry, agent_runtime refactor (tool dispatch through registry instead of elif chain), Notion MCP server wiring, CLI + doctor + tests + docs.
**Built:**
- `aureon_agent/mcp_client.py` (new, ~250 LoC): `MCPClient` class for single-server stdio connections + `MCPManager` for multi-server management. Full lifecycle: connect → list_tools → call_tool → disconnect. Tool schema translation (MCP inputSchema → OpenAI function parameters). Tool name prefixing (`mcp_<server>_<tool>`). Graceful failure: server crash → error dict returned, no agent crash.
- `aureon_agent/tool_registry.py` (new, ~160 LoC): `ToolRegistry` merges 3 backends (skills, inline, MCP) into one flat tool list for the LLM. Deduplication: MCP wins on name collision (WARN logged). Dispatch routes to correct backend. Internal MCP metadata stripped from LLM-facing schemas. Cache invalidation via `refresh()`.
- `agent_runtime.py` (refactored): Extracted 16 hardcoded tool schemas to `INLINE_TOOL_SCHEMAS` list. Replaced 20-line elif dispatch chain with `registry.dispatch(name, args, context)`. Tools registered via `setup_registry()` → `_register_inline_tools()`. All async handler wrappers for sync tools (FileTool.read_file, TodoTool, etc.). Backward-compatible: falls back to skill-only dispatch if no registry set.
- `aureon_agent/cli.py`: Added `_parse_mcp_servers()` (reads `NOTION_TOKEN`/`GITHUB_MCP_TOKEN` from env), `MCPManager` wiring (connect at boot, disconnect on shutdown), `ToolRegistry` construction + `agent.setup_registry()`.
- `aureon_agent/__main__.py`: Added `aureon-agent mcp list` CLI subcommand (connects to configured servers, shows Rich table of tools).
- `aureon_agent/doctor.py`: Added `check_mcp_servers()` — verifies env vars + binary presence for configured servers.
- `requirements.txt`: Added `mcp>=1.0`.
- `docs/mcp.md` (new): Architecture diagram, configuration guide, naming conventions, failure handling, CLI, security model, troubleshooting.
- `tests/test_mcp_client.py` (new, 14 tests): Schema translation, tool prefixing, call routing, error handling (not connected, server crash, missing binary).
- `tests/test_tool_registry.py` (new, 12 tests): Merging, deduplication, dispatch routing, cache refresh, backend query.
**Verified:** 63/63 pytest tests pass (37 existing + 26 new). Zero regressions.
**Key design decisions:**
- Tool schemas extracted to a list but kept inline (not moved to separate files) — they're tightly coupled to agent state (cron tools access DB, clarify pauses the loop).
- MCP tools prefixed `mcp_<server>_<tool>` to avoid collision with local skills.
- Registry uses 3-tier merge order: skills → inline → MCP. Last wins on collision.
- HTTP/SSE transport deferred to Phase 7.2 (Gmail needs it).

---

## 2026-07-15 — Phase 9.5: Cron tools + TUI banner + bug fixes (this session)
**Did:** Added 5 cron tools to the agent's tool registry (so Captain can create/list/remove cron jobs via Telegram chat), replaced the TUI banner with a pixel-art version matching the README SVG, and fixed 4 bugs that were causing "(no response from LLM)" on Telegram.
**Cron tools (commit `062702f`):**
- 5 new tools in `agent_runtime.py`: `cron_create`, `cron_list`, `cron_remove`, `cron_pause`, `cron_resume`
- All 5 call the same `cron_db.py` + `cron_schedule.py` as the CLI (no duplication)
- `_cron_create()` writes to `data/cron_jobs.db`, calculates next run via `cron_schedule.calc_next_run()`, defaults `chat_id` to `TELEGRAM_ALLOWED_CHATS`
- `_cron_list()` reads from DB, returns formatted string with job ID, status, schedule, next run
- `_cron_remove/pause/resume()` — thin wrappers around DB updates
**TUI banner (commit `fcc49d0`):**
- `aureon_agent/tui.py:print_banner()` now renders pixel-art `AUREON-AGENT` wordmark
- 5x7 pixel font (same as `scripts/generate_banner.py`) rendered with unicode block chars (█)
- Warm orange gradient: top row `#FFD24A`, middle `#FF8A2B`, bottom `#E85D04` (matching `assets/banner.svg`)
- Top + bottom accent bars in `#E85D04`
- Version tagline + GitHub URL at bottom
- Shows in: `aureon-agent-doctor`, `aureon-agent setup`, `aureon-agent postinstall`
**Bug fixes:**
- `1015753`: `channels/telegram.py:84-95` — when LLM returns empty final response, fall back to streamed text from `state["text"]` (accumulates all rounds' tokens via `on_token` callback). If both empty, show "(no response from LLM — try again or simplify your message)".
- `c42d136`: `aureon_agent/tools/terminal.py` — accept string commands (not just lists). LLMs naturally send `"ls -la /path"` (string), but the tool rejected them with "command must be a list". Now `shlex.split()` the string. JSON schema changed to `oneOf: [array, string]`.
- `3894977`: `aureon_agent/tools/terminal.py` — expand `~` in path-like arguments (`subprocess.run` with `shell=False` doesn't expand `~`). `agent_runtime.py` — force final summary call after `MAX_TOOL_ROUNDS=5` with no text: extra LLM call without tools, system prompt says "You have used all your tool calls. Now provide a final text response."
- `503f2ce`: `agent_runtime.py` — fix cron tools DB path: single `dirname(__file__)` not double. `agent_runtime.py` is at project root, not inside `aureon_agent/`. Was looking for `data/cron_jobs.db` at `~/dev-shared/projects/data/` instead of `~/dev-shared/projects/aureon-agent/data/`.
**Stale `.pyc` lesson:** Bot started at 00:18:08 with fix deployed at 00:17:19, but returned "No cron jobs configured" until restarted again. Root cause: Python used a stale `.pyc` (compiled at 00:17:07 from pre-fix source) because `.pyc` timestamp was newer than source timestamp. Fix: delete `__pycache__/agent_runtime*.pyc` + restart. See lessons.md L-006.
**Verified on dev at `503f2ce`:**
- 37/37 tests pass (13 existing + 24 cron)
- `aureon-agent cron list` shows `homelab-health-daily` job (matches Hermes)
- Bot responds to all Telegram messages (no more "(no response)")
- `_cron_list()` returns real job `31168652` from Telegram chat
- TUI banner renders pixel-art wordmark in orange gradient
**Branch state:** `dev` at `503f2ce`, 2 branches (dev, main), 0 open PRs
**Modified:** `agent_runtime.py` (+188 LoC for cron tools + DB path fix), `aureon_agent/tui.py` (+69 LoC for pixel banner), `channels/telegram.py` (+15 LoC for streamed fallback), `aureon_agent/tools/terminal.py` (+22 LoC for string + `~` expansion), `tasks/todo.md`, `tasks/DEVLOG.md`, `tasks/lessons.md`

---

## 2026-07-14 — Phase 9: Cron Scheduler (local session, branch `feat/aureon-agent-cron-scheduler`)
**Did:** Built the full cron scheduler subsystem per `tasks/kickoff-cron-scheduler.md`. Same architecture as Hermes + OpenClaw: scheduler ticks every 60s inside the bot process, checks for due jobs, spawns isolated agent runs via `agent_runtime.run()`, delivers output to Telegram/Discord via `channels/router.py`. Jobs persist in SQLite across restarts.
**Built:**
- `aureon_agent/cron_db.py` (new, ~170 lines): SQLite persistence with `cron_jobs` + `cron_runs` tables, WAL mode, full CRUD (`add_job`, `get_job`, `list_jobs`, `update_job`, `remove_job`, `get_due_jobs`, `add_run`, `finish_run`, `list_runs`). Same aiosqlite pattern as `memory.py` and `session_manager.py`.
- `aureon_agent/cron_schedule.py` (new, ~115 lines): Schedule parsing for 3 types — `cron` (5-field Vixie via `croniter`), `interval` (Nm/Nh/Nd), `at` (ISO 8601). Top-of-hour staggering (0-5 min random offset for `:00` cron expressions, disable with `--exact`). Timezone support via `zoneinfo`.
- `aureon_agent/cron.py` (new, ~230 lines): `CronScheduler` class — asyncio background task with `start()`/`stop()` lifecycle. `_loop()` ticks every 60s. `_tick()` finds due jobs. `_run_job()` creates isolated `cron:<job_id>:<timestamp>` sessions, calls `agent_runtime.run()` with `asyncio.wait_for(timeout)`, handles success/timeout/error, delivers via `router.send_message()`, reschedules or auto-deletes. `_handle_overdue_jobs()` on startup: recurring overdue → reschedule to future, one-shot overdue → delete. Grace period shutdown for in-flight jobs.
- `aureon_agent/cron_cli.py` (new, ~280 lines): Full CLI subcommand group (`aureon-agent cron list|create|pause|resume|run|remove|runs|status`). Rich tables for output. `--name`, `--prompt`, `--skills`, `--deliver`, `--chat-id`, `--model`, `--timeout-sec`, `--repeat`, `--tz`, `--exact`, `--disabled` options on create.
- `skill_loader.py`: Added `get_tools_subset(names: list[str])` for per-job skill loading. Backward-compatible.
- `aureon_agent/cli.py`: Wired `CronScheduler` into bot startup (after channel registration, before `shutdown.wait()`) and shutdown (before `router.stop_all()`).
- `aureon_agent/__main__.py`: Registered `cron` subcommand group with argparse dispatch.
- `aureon_agent/doctor.py`: Added `check_cron_scheduler()` — verifies DB readable, counts enabled jobs, checks for stuck runs (>10 min).
- `requirements.txt`: Added `croniter>=1.4`.
- `docs/cron.md` (new): User-facing docs — schedule types, CLI commands, delivery options, isolation model, heartbeat vs cron comparison, troubleshooting.
- `tests/test_cron.py` (new, 24 tests): Schedule detection, interval parsing, next-run calculation, staggering, DB CRUD, scheduler tick, success/timeout/error paths, one-shot auto-delete, overdue rescheduling, skill subset loading.
**Verified:** 37/37 pytest tests pass (13 existing + 24 new). No regressions.
**Modified:** `aureon_agent/cron_db.py` (new), `aureon_agent/cron_schedule.py` (new), `aureon_agent/cron.py` (new), `aureon_agent/cron_cli.py` (new), `skill_loader.py`, `aureon_agent/cli.py`, `aureon_agent/__main__.py`, `aureon_agent/doctor.py`, `requirements.txt`, `docs/cron.md` (new), `tests/test_cron.py` (new), `tasks/todo.md`, `tasks/DEVLOG.md` (this entry).

---

## 2026-07-13 — Phase 6.5 closeout + plan-node cherry-pick (this session)
**Did:** Final audit of Phase 6.5. Captain asked: "Audit all the work that is in dev branch, if all good merge to dev and we are done for today". Verified 4 work items shipped, found 1 missing merge, cherry-picked it, wrote closing DEVLOG/lessons/todo.
**Audit findings:**
- Tier 1 (terminal, file, web): in dev at `4ca4801` ✅
- Tier 2 (todo, clarify): in dev at `c42376d` ✅
- Tier 3 (subagent dispatch): in dev at `9dc6006` ✅
- Tier 4 (plan-node hard block v2): **NOT in dev** — Captain's report was wrong; `f671a59` was only on `origin/feat/aureon-agent-plan-node-hard-block` branch, not merged. Cherry-picked to dev at `ea06f46`. Now `plan_node.py` is 96 lines (v2: count_features, has_plan, require_plan), `tests/test_plan_node.py` exists, doctor shows "Plan Node OK".
- Bug fix `740f208`: missing `import shutil` in `aureon_agent/doctor.py` for `check_claude_cli` (subagent agent forgot it).
**Verified on dev at `ea06f46`:**
- 13/13 pytest tests pass (config 3 + doctor 1 + plan_node 2 + setup 1 + subagent 1 + tier2_tools 2 + tools 3)
- `aureon-agent-doctor`: 7/8 green, 1 expected warning (systemd no-DBUS in sub-process)
- plan_node v2 live: 3+ step request returns ok=False with reason, read-only bypasses, magic phrases ("just do it") bypass with WARN log
- 5 stale feature branches deleted (work is in dev now)
**Branch state:** dev at `ea06f46`, main at init, 0 open PRs
**Modified:** tasks/DEVLOG.md, tasks/lessons.md, tasks/todo.md

---

## 2026-07-13 — Session compaction (local session, branch `feat/aureon-agent-session-compaction`)
**Did:** Built model-aware session compaction per `tasks/kickoff-session-compaction.md` (confirmed doc, pure-docs commit `225143a` on `dev`, no prior code). Old turns get LLM-summarized once history exceeds a per-model token threshold; recent turns stay verbatim. View-layer only — `session_manager.py`'s `messages` table is never rewritten, compaction only reshapes what gets sent to the LLM per-call.
**Built:**
- `aureon_agent/models.py` (new): `MODEL_CONTEXT_WINDOWS` lookup table + `get_context_window(model)`, unknown-model fallback to 32K with a WARN log.
- `compaction/counter.py` (new): `count_tokens_text`/`count_tokens_messages` via `tiktoken` `cl100k_base`, falls back to `len(text)//4` if tiktoken isn't importable. `needs_compaction(current, threshold)`.
- `compaction/threshold.py` (new): `compute_compact_threshold(model, system_prompt)` = `context_window - 4096 (reserved response) - system_prompt_tokens`; returns 0 + ERROR log if system prompt >50% of context window (safety skip). `compute_recent_verbatim_size(threshold)` = `min(4000, threshold * 0.2)`.
- `compaction/summarizer.py` (new): `Summarizer.summarize(messages)` — one LLM call (`httpx.AsyncClient`, OpenAI-compat `/chat/completions`), 300 max output tokens, 30s timeout, degraded fallback (truncated transcript, ≤500 chars) on timeout/error — never raises.
- `compaction/log.py` (new): `CompactionLog` — append-only `aiosqlite` audit trail in **`data/compaction_log.db`** (separate file from `sessions.db`/`memory.db` by design). Records `tokens_before/after`, `summary_text`, `model_used`, `context_window_used`, `status`. `list_recent(session_id=, model=, limit=)` for querying.
- `agent_runtime.py`: `run()` now calls `_maybe_compact(messages, session_id, system_prompt)` right after building the message list. `_maybe_compact`/`_compact` implement sliding-window + LLM-summary: recent-verbatim tail kept as-is, everything older collapsed into one `{"role": "system", "content": "[compacted-history-summary] ..."}` message. Fail-open: any error (timeout, missing model, system-prompt-too-big) logs and falls back to the full uncompacted history — compaction never breaks a live turn. Gated by `AUREON_COMPACTION_ENABLED` env flag, **off by default**. New counters `compactions_run_total`/`compactions_skipped_total`.
- `aureon_agent/__main__.py`: `compaction-log` subcommand (`--last`, `--session`, `--model`) prints the audit trail as a Rich table.
- `aureon_agent/doctor.py`: `check_compaction_log()` (DB readable, warns if stale >7 days idle) and `check_model_known()` (warns if active model isn't in `MODEL_CONTEXT_WINDOWS`) added to the health-check list.
- `pyproject.toml`: added `"compaction"` to `[tool.setuptools] packages`. `requirements.txt`: added `tiktoken>=0.7`.
- `tests/test_compaction_counter.py`, `tests/test_compaction_threshold.py`, `tests/test_compaction_summarizer.py`, `tests/test_compaction_integration.py` — 24 tests across counter/threshold/summarizer/integration, all passing; live-verified against local Ollama (`_maybe_compact` collapsed 31320→3944 tokens on first real input).
- `tasks/DEVLOG.md`: this entry.
**Merged:** PR #16 at commit `d3cf3b2` into `dev`.
**Modified:** `aureon_agent/models.py` (new), `compaction/{__init__,counter,threshold,summarizer,log}.py` (new), `agent_runtime.py`, `aureon_agent/__main__.py`, `aureon_agent/doctor.py`, `aureon_agent/cli.py`, `pyproject.toml`, `requirements.txt`, `tests/test_compaction_*.py` (4 new test files), `tasks/DEVLOG.md` (this entry).

---

## 2026-07-13 — Phase 6.5: Plan-node hard block v2 (local session)
**Did:** Promoted the soft-warning plan-node check to a hard block that catches 3+ step tasks before starting the ReAct loop. Branched `feat/aureon-agent-plan-node-hard-block` off `dev`.
**Built:** Updated `plan_node.py` with structured `require_plan` and `count_features` containing logic for imperative verbs, conjunctions, URLs, and file paths. Modified `agent_runtime.py` to hard block before the ReAct loop and return the rejection reason. Added tests in `tests/test_plan_node.py` and `doctor.py` check.
**Verified:** Tests passing, doctor passing.
**Modified:** `plan_node.py`, `agent_runtime.py`, `aureon_agent/doctor.py`, `tests/test_plan_node.py`, `tasks/todo.md`, `tasks/DEVLOG.md`.

## 2026-07-13 — Phase 6.5: Subagent dispatch (local session)
**Did:** Built `delegate_task` tool to dispatch parallel work to a subagent (`claude-code` CLI), complete with sandboxing and audit logging. Branched `feat/aureon-agent-subagent-dispatch` off `dev`.
**Built:** `aureon_agent/subagent/` package (`base.py`, `task.py`, `sandbox.py`, `claude_code.py`, `log.py`, `tool.py`, `__init__.py`). Added `aureon-agent subagent-log` CLI and `check_claude_cli` doctor check. Registered `delegate_task` in `agent_runtime.py`.
**Verified:** Tests passing, doctor passing.
**Next:** Plan-node hard block (v2).
**Modified:** `aureon_agent/subagent/*`, `aureon_agent/__main__.py`, `aureon_agent/doctor.py`, `agent_runtime.py`, `tasks/DEVLOG.md`, `tasks/todo.md`.

## 2026-07-13 — Phase 6.5: Tier 2 tools (local session)
**Did:** Built Tier 2 tools (`todo` and `clarify`), adding the ability for the agent to maintain its own plan and ask questions before destructive actions. Branched `feat/aureon-agent-tier2-tools` off `dev`.
**Built:** `aureon_agent/tools/todo.py` (`todo_read`, `todo_write`, `todo_add`), `aureon_agent/tools/clarify.py` (`clarify`). Updated `channels/router.py` with `pending_clarifications` and `send_message` capabilities to properly pause the ReAct loop and await a user reply. Registered the tools in `agent_runtime.py`.
**Verified:** Tests passing for Todo validations and operations. CLI `clarify-log` command works and formats tool audit entries properly. 
**Next:** Subagent dispatch (delegate_task).
**Modified:** `aureon_agent/tools/todo.py`, `aureon_agent/tools/clarify.py`, `aureon_agent/__main__.py`, `agent_runtime.py`, `channels/router.py`, `docs/tools.md`, `tasks/DEVLOG.md`.

## 2026-07-13 — Phase 6.5: Tier 1 tools (local session)
**Did:** Built Tier 1 tools (`terminal`, `file`, `web`) mirroring Hermes shapes. Added `WorkspaceBoundTool` base class and `tool_log.db` audit logging. Branched `feat/aureon-agent-tier1-tools` off `dev`.
**Built:** `aureon_agent/tools/` package (`base.py`, `log.py`, `confirm.py`, `terminal.py`, `file.py`, `web.py`, `__init__.py`). Added `aureon-agent tool-log` CLI and `check_tools_allowlist` to doctor. Updated `agent_runtime.py` and `channels/router.py` to register tools and wire Captain confirmation callbacks. Added `docs/tools.md` and tests in `tests/test_tools.py`. Installed `beautifulsoup4`.
**Verified:** Pytest suite passes. Tools correctly restrict to allowlist paths and block unconfirmed destructive actions.
**Next:** Tier 2 tools (todo, clarify).
**Modified:** `requirements.txt`, `aureon_agent/__main__.py`, `aureon_agent/doctor.py`, `agent_runtime.py`, `channels/router.py`, `tasks/DEVLOG.md`.

## 2026-07-13 — Session compaction (local session, branch `feat/aureon-agent-session-compaction`)
**Did:** Built model-aware session compaction per `tasks/kickoff-session-compaction.md` (confirmed doc, pure-docs commit `225143a` on `dev`, no prior code). Old turns get LLM-summarized once history exceeds a per-model token threshold; recent turns stay verbatim. View-layer only — `session_manager.py`'s `messages` table is never rewritten, compaction only reshapes what gets sent to the LLM per-call.
**Built:**
- `aureon_agent/models.py` (new): `MODEL_CONTEXT_WINDOWS` lookup table + `get_context_window(model)`, unknown-model fallback to 32K with a WARN log.
- `compaction/counter.py` (new): `count_tokens_text`/`count_tokens_messages` via `tiktoken` `cl100k_base`, falls back to `len(text)//4` if tiktoken isn't importable. `needs_compaction(current, threshold)`.
- `compaction/threshold.py` (new): `compute_compact_threshold(model, system_prompt)` = `context_window - 4096 (reserved response) - system_prompt_tokens`; returns 0 + ERROR log if system prompt >50% of context window (safety skip). `compute_recent_verbatim_size(threshold)` = `min(4000, threshold * 0.2)`.
- `compaction/summarizer.py` (new): `Summarizer.summarize(messages)` — one LLM call (`httpx.AsyncClient`, OpenAI-compat `/chat/completions`), 300 max output tokens, 30s timeout, degraded fallback (truncated transcript, ≤500 chars) on timeout/error — never raises.
- `compaction/log.py` (new): `CompactionLog` — append-only `aiosqlite` audit trail in **`data/compaction_log.db`** (separate file from `sessions.db`/`memory.db` by design). Records `tokens_before/after`, `summary_text`, `model_used`, `context_window_used`, `status`. `list_recent(session_id=, model=, limit=)` for querying.
- `agent_runtime.py`: `run()` now calls `_maybe_compact(messages, session_id, system_prompt)` right after building the message list. `_maybe_compact`/`_compact` implement sliding-window + LLM-summary: recent-verbatim tail kept as-is, everything older collapsed into one `{"role": "system", "content": "[compacted-history-summary] ..."}` message. Fail-open: any error (timeout, missing model, system-prompt-too-big) logs and falls back to the full uncompacted history — compaction never breaks a live turn. Gated by `AUREON_COMPACTION_ENABLED` env flag, **off by default**. New counters `compactions_run_total`/`compactions_skipped_total`.
- `aureon_agent/__main__.py`: `compaction-log` subcommand (`--last`, `--session`, `--model`) prints the audit trail as a Rich table.
- `aureon_agent/doctor.py`: `check_compaction_log()` (DB readable, warns if stale >7 days idle) and `check_model_known()` (warns if active model isn't in `MODEL_CONTEXT_WINDOWS`) added to the health-check list.
- `pyproject.toml`: added `"compaction"` to `[tool.setuptools] packages`. `requirements.txt`: added `tiktoken>=0.7`.
**Test-writing gotcha:** naive `"x" * N` strings don't give `N/4` tokens under `cl100k_base` BPE — repeated characters compress far more (measured `"x"*8000` → 1000 tokens, an 8x ratio). Threshold tests needed a `_text_with_token_count(n)` helper (encode a base phrase → repeat/truncate ids to exactly `n` → decode) to get exact, not approximate, token counts. Even then, decode→re-encode can shift a BPE merge boundary by a few dozen tokens, so exact-threshold assertions measure the actual re-encoded system-prompt token count rather than hardcoding an assumed value.
**Verified:** `pytest tests/` 24 passed (new: `test_compaction_counter.py`, `test_compaction_threshold.py`, `test_compaction_summarizer.py`, `test_compaction_integration.py` — hand-rolled fake `httpx.AsyncClient` context managers for LLM mocking, no `respx`/`pytest-asyncio` in this project). `python tests/smoke.py` 5/5 pass. Live-verified against the real local Ollama instance: 120 synthetic filler messages, `AUREON_COMPACTION_ENABLED=1` → compaction fired, 31320→3944 tokens, summary coherent, audit log recorded `context_window_used=32768` correctly (test DB deleted after). `python -m aureon_agent doctor` shows both new checks cleanly against the live `.env`/Telegram bot. `ruff check` clean on all new/modified files.
**Deferred:** live-channel round-trip test (30+ real Telegram messages triggering auto-compaction, confirmed non-firing on a 1M-context model) — only verified via direct `_maybe_compact` calls so far, not through the Telegram adapter. Tracked in `tasks/todo.md`.
**Next:** PR to `dev`. Then either the live-channel compaction test, or move to Phase 6 remainder (plan-node hard block, subagent dispatch) / Phase 7 (MCP first server).
**Modified:** `aureon_agent/models.py` (new), `compaction/__init__.py` (new), `compaction/counter.py` (new), `compaction/threshold.py` (new), `compaction/summarizer.py` (new), `compaction/log.py` (new), `agent_runtime.py`, `aureon_agent/cli.py`, `aureon_agent/__main__.py`, `aureon_agent/doctor.py`, `pyproject.toml`, `requirements.txt`, `tests/test_compaction_*.py` (new, 4 files), `CLAUDE.md`, `tasks/todo.md`, `tasks/DEVLOG.md` (this entry).

---

## 2026-07-13 — PID lock + systemd unit install (local session, PR #9)
**Did:** Fixed the "two bots on one token" problem that caused Telegram 409 Conflict errors. Two related fixes shipped together on `feat/aureon-agent-pid-lock-and-systemd`.
**Built:**
- `aureon_agent/pidlock.py` (new, 110 lines): `acquire_lock()` / `release_lock()` on `~/.cache/aureon-agent.pid`. O_EXCL for atomic race detection. Stale PID takeover (detects dead PID, takes over). Re-entrant same-process (re-acquire succeeds). `_pid_alive()` checks `/proc/<pid>/status` State line to skip zombies.
- `aureon_agent/cli.py`: `acquire_lock()` at top of `main()`, exits 1 with clear error if another instance holds. `try/finally` around `shutdown.wait()` guarantees `release_lock()` on SIGINT/SIGTERM/exception.
- `systemd/aureon-agent.service` (new, 620 bytes): committed template, source of truth for the daemon install. Points at `WorkingDirectory=/home/radxa/dev-shared/projects/aureon-agent` and `ExecStart=/home/radxa/dev-shared/projects/aureon-agent/.venv/bin/python -m aureon_agent`. `Restart=on-failure`, `RestartSec=10`. Standard journal output.
- `aureon_agent/setup.py` `run_systemd_setup()`: reads from `systemd/aureon-agent.service` (canonical, no inline f-string). Lingering check via `/var/lib/systemd/linger/<user>`. `loginctl enable-linger` if not enabled. **Stop-then-start the service** (the dance that caused the 409 earlier — manually running instance → service would be 2 polling bots). All 4 systemctl calls best-effort: warn on no DBUS session, don't fail wizard.
- Minor setup.py fixes: `import logging` + `logger`, `os.getlogin()` fallback to pwd lookup (fails in non-tty contexts), `/var/lib/systemd/linger` is a directory not a file (use `iterdir()`).
**Verified:**
- pytest tests/test_config.py tests/test_doctor.py tests/test_setup.py: 5/5 pass
- python tests/smoke.py: 5/5 pass
- First instance boots, writes `~/.cache/aureon-agent.pid`, polls Telegram clean
- Second instance refused with: `another aureon-agent is already running (pid 2364609). If that's stale, remove ~/.cache/aureon-agent.pid and retry.`
- systemd unit installed at `~/.config/systemd/user/aureon-agent.service`
- Live `aureon-agent doctor` on merged dev: 6/8 green, 1 expected warning (systemd not started in this DBUS-less sub-process), 0 errors
**Merged:** PR #9 (https://github.com/vkkatariya/aureon-agent/pull/9) at commit `6bf69c6` into `dev`.
**Next:** Captain to run `tmux attach -t cc-aureon-agent` and `aureon-agent setup --section daemon` from a real terminal to activate the systemd service. After that: Phase 6 (plan-node hard block, subagent dispatch via Hermes `delegate_task`) or Phase 7 (MCP first server — Notion).
**Modified:** `aureon_agent/pidlock.py` (new), `aureon_agent/cli.py`, `aureon_agent/setup.py`, `systemd/aureon-agent.service` (new), `tasks/DEVLOG.md` (this entry).

---

## 2026-07-13 — Banner + audit fix + PR cleanup (local session, PRs #6 #7 #8)
**Did:** Three PRs merged in sequence after audit. Each had its own issues caught + fixed.
**Built:**
- `assets/banner.svg` (new, 28KB, 1200x300) + `scripts/generate_banner.py` (new, 207 lines): pixel-style "AUREON-AGENT" wordmark, 5x7 font, 12px pixel size, yellow→orange→red gradient, drop shadow, dark gradient background, accent bars, caption strip. Hand-crafted `<rect>` elements, no external font deps, renders perfectly in GitHub README viewer.
- `README.md`: full rewrite mirroring Hermes-Agent + OpenClaw structure. Banner → tagline → badge row → elevator pitch → stack table → install (3 blocks: first install, reconfigure, ops) → what it does → architecture → layout → setup modes → safety → status → dev → acknowledgments. 171 lines.
- Phase 8 added to `tasks/todo.md`: 4 sub-phases, 12 sub-tasks, full acceptance criteria, references to OpenClaw docs + Hermes CLI + OpenClaw health check.
**Audit fixes (caught during live `aureon-agent doctor` run on PR #8's branch):**
- `aureon_agent/doctor.py`: `check_telegram()` + `check_ollama()` were using `AureonConfig.from_env()` which reads empty `os.environ` when run as standalone CLI. Doctor showed "Telegram API: Not configured" even with valid token in `.env`. Fixed by adding `ENV_PATH` constant at module level + switching to `AureonConfig.from_file(ENV_PATH)`. Telegram now shows `Bot: @aureon_agent_bot` ✅.
- `aureon_agent.egg-info/` was committed (pip install -e . output, not source). Added `aureon_agent.egg-info/` + `*.egg-info/` to `.gitignore`, ran `git rm -rf --cached`.
- Conflict in `tasks/todo.md` (PR #8 vs PR #6): kept kickoff's detailed sub-tasks 1-12, marked all done (✅ PR #8), dropped the agent's abbreviated duplicate list.
**PRs:**
- PR #6 (kickoff prompt + todo entry, 391 lines, docs only) — merged via `gh pr merge`
- PR #7 (banner only, 754 lines) — closed as redundant (banner files were already in PR #8's commit `eac816d` because the agent cherry-picked them)
- PR #8 (interactive setup script + CLI tools, 1715 lines, 21 files) — rebase-merged locally with conflict resolution in `tasks/todo.md`, dev at `4b13ecb`
- **Agent's gap:** did not open a PR before signing off the setup-script session; Captain's audit caught this and opened it manually.
**Verified:** `aureon-agent-doctor` on merged dev: 6/8 green, 1 expected warning (systemd not installed, deferred to v1), 0 errors. All 5/5 pytest tests pass, 5/5 smoke tests pass.
**Modified:** `assets/banner.svg` (new), `scripts/generate_banner.py` (new), `README.md`, `tasks/todo.md`, `tasks/DEVLOG.md`, `aureon_agent/doctor.py`, `aureon_agent/cli.py`, `.gitignore`.

---

## 2026-07-13 — Phase 8: Setup script (local session)
**Did:** Built all files from Phase 8 setup script (sub-tasks 1-12), on top of Phase 0-5. Branched `feat/aureon-agent-setup-script` off `dev`.
**Built:** `aureon_agent/__init__.py`, `__main__.py` (CLI glue with argparse), `config.py` (dataclass, `python-dotenv`), `tui.py` (Rich/Questionary helpers), `setup.py` (interactive wizard with model/channel/daemon steps), `doctor.py` (health checks), `postinstall.py`. Added `rich` and `questionary` to `requirements.txt`.
**Verified:** `aureon-agent doctor` runs perfectly. `aureon-agent setup` tested via `test_setup.py`. `tests/smoke.py` and `tests/test_agent_loop.py` pass.
**Next:** Captain to run `aureon-agent setup` to complete the configuration and verify the systemd daemon.
**Modified:** `pyproject.toml`, `requirements.txt`, `tasks/todo.md`, `README.md`, `docs/setup-script.md`, `aureon_agent/*`, `tests/test_*.py`.

## 2026-07-13 — Phase 2-5: core runtime, channels, entry, verification (local session)
**Did:** Built all remaining files from tasks/kickoff-aureon-agent.md Phases 2-5 (sub-tasks 3-14), on top of the Phase 0/1 setup already merged into `dev`. Branched `feat/aureon-agent-bootstrap` off `dev` (not `main` — `main` was stale, missing the vendored tiny-openclaw reference and DEVLOG/todo/lessons scaffolding that already live on `dev`).
**Built:** `memory.py` + `session_manager.py` (aiosqlite, WAL, per-session_id asyncio.Lock), `skill_loader.py` (PyYAML frontmatter parsing, hot-reload via watchfiles), `context_builder.py` (SOUL+IDENTITY+skills+notes+time, ~1.3K tokens measured), `agent_runtime.py` (ReAct loop against Ollama's OpenAI-compat streaming endpoint, MAX_TOOL_ROUNDS=5, local→cloud fallback on connect/timeout, auto-clarity override regex for destructive commands), `plan_node.py` (soft warning, logs only), `lessons.py` (append-only, newest-first, matches the doctrine template at `~/.openclaw/workspace/tasks/lessons.md`), `channels/{base,router,telegram,discord}.py` (Router owns session bookkeeping + `/lesson` command; adapters own platform I/O, streaming throttle, chunking), `main.py` (wires everything, SIGINT/SIGTERM, optional 127.0.0.1 health endpoint), `tests/{smoke,test_agent_loop}.py`.
**Architecture decision — skill format mismatch:** the kickoff spec assumed all 8 OpenClaw skills follow Tiny-OpenClaw's `tools` + `execute()` handler.py contract. Checked `~/.openclaw/workspace/skills/*` directly: none of the 8 have a `handler.py` — they're prose-only SKILL.md files (Claude-Code-skill style), meant for an LLM to read and follow, not Python functions to call. Resolved by having `skill_loader.py` support both shapes: real `handler.py` skills load as before (forward-compatible, none exist yet); prose-only skills get one synthesized tool, `read_skill_<name>`, whose `execute()` returns the skill body text so the agent can pull it into context on demand. Documented in `skill_loader.py` module docstring.
**Model default fixed:** kickoff spec's `OLLAMA_MODEL` default (`minimax-m3`) only exists on the cloud endpoint (`ollama-cloud` provider in `~/.openclaw/openclaw.json`). The local endpoint (`http://127.0.0.1:11434/v1`, the actual default `OLLAMA_BASE_URL`) only proxies `minimax-m2.5:cloud` and `gemma4:31b-cloud`. Changed default to `minimax-m2.5:cloud` in `main.py`, `tests/test_agent_loop.py`, README — verified against the live local Ollama instance.
**CI fixes (found while lint-testing locally):** `ci.yml`'s `ruff check .` would also lint its own freshly-created `.venv/` (1011 false-positive errors reproduced locally) — added `--exclude .venv --exclude references`. Path filters (`'*.py'`) didn't match `channels/**/*.py`, so channel changes wouldn't trigger CI — broadened to `'**/*.py'`. Added `.venv/` to `.gitignore` (wasn't there before).
**Verified:** `python tests/smoke.py` and `python tests/test_agent_loop.py` both pass live against local Ollama (8 skills load, Memory/SessionManager roundtrip, context builder ~1305 tokens, real streamed agent response). `python main.py` boots clean with no channel tokens set (warns, idles, shuts down cleanly on SIGINT). `ruff check` clean on all new source files.
**Not done (deferred, per CONTEXT.md "What's NOT in v1"):** live Telegram/Discord bot test (needs real tokens + a chat to test from — Definition of Done items for that are unverified pending Captain running it with real credentials), systemd service, plan-node hard block, MCP integration (Phase 7, separately scoped).
**Next:** Captain to supply `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_CHATS` (+ optionally `DISCORD_BOT_TOKEN`) in `.env` and smoke-test a real chat round-trip before merging to `dev`.
**Modified:** memory.py, session_manager.py, skill_loader.py, context_builder.py, agent_runtime.py, plan_node.py, lessons.py, channels/*.py, main.py, tests/*.py, requirements.txt (+pyyaml), .gitignore (+.venv/), .github/workflows/ci.yml (ruff exclude + path filters), README.md (env vars), tasks/todo.md (Phase 2-5 checked off).

## 2026-07-13 init — Hermes project-init skill (partial)
**Did:** Created full project dev setup for aureon-agent
**Stack:** Python 3.12 + httpx + aiosqlite + python-telegram-bot + discord.py + Ollama (local + cloud)
**Infra:** athena (single Python process, Tailscale, no Docker, no 0.0.0.0 binds)
**State:** Bootstrap files (AGENTS.md, CONTEXT.md, README.md, CLAUDE.md, .gitignore, requirements.txt, kickoff spec) pre-existed from prior Hermes bootstrap. Added the 4 missing skill-required files (tasks/DEVLOG.md, tasks/todo.md, tasks/lessons.md, .github/workflows/ci.yml). Workspace symlinks to ~/.openclaw/workspace/ doctrine already wired. Git initialized, GitHub repo live, CI pipeline active.
**Decided:** Public GitHub repo (open-source from day 1). `main` + `dev` branch model per skill. Reuse existing AGENTS.md/CONTEXT.md/README.md from prior bootstrap (don't regenerate — per skill partial-setup rules).
**Next:** Phase 1 sub-tasks 1-2 from tasks/kickoff-aureon-agent.md (workspace symlinks + bootstrap already done, so jump to sub-task 3: SQLite Memory + SessionManager).
**Modified:** tasks/DEVLOG.md, tasks/todo.md, tasks/lessons.md, .github/workflows/ci.yml, .git/ (init), origin/main (push), origin/dev (push)
