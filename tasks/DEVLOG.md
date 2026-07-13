# Dev Log
> Append-only. Agents write an entry at the end of every session. Newest at top.

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
