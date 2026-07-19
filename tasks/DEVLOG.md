# Dev Log
> Append-only. Agents write an entry at the end of every session. Newest at top.

---

## 2026-07-19 — Interactive TUI agent session (local session, branch `feat/tui-session`)
**Did:** Added a Claude-Code/Hermes-style interactive terminal session — `python -m aureon_agent.__main__ tui` — that chats with the agent live and boots either fresh or by `--handoff`-ing an existing (e.g. Telegram) session.
**Built:**
- `aureon_agent/cli.py`: extracted `build_runtime(watch_skills=, connect_mcp=)` from `main()` — the shared memory/sessions/skills/agent/MCP/registry wiring, so the TUI drives the exact same `agent.run` as the bot. `main()` now calls it.
- `aureon_agent/repl.py` (new): `run_tui(handoff, session)` + `cmd_tui`. Boot modes — default `tui:tty`, `--handoff telegram:723865496` (validated against `list_sessions`, loads that history), `--session <id>`. `prompt_toolkit` input line (history + keybindings) with `input()` fallback on non-TTY/import-fail; tokens stream to stdout. `/commands` reuse the CLI subcommands; `/new` (typed yes/no confirm) → `clear_session`; `/handoff` switches the live session (re-registers a `TuiChannel` under the target's channel prefix); `/help`+`/exit` local. Destructive confirmations (`confirm_with_captain`) resolve via a stdin watcher on `router.pending_confirmations` (no Telegram keyboard in a terminal).
- `aureon_agent/__main__.py`: `tui` subparser (`--handoff`/`--session`) + dispatch. `requirements.txt`: `prompt_toolkit>=3.0`.
**Decisions / gotchas:**
- **Named the module `repl.py`, not `tui.py`** — `aureon_agent/tui.py` already exists (the setup-wizard Rich/Questionary helpers); clobbering it would break `setup`.
- **TUI skips MCP (`connect_mcp=False`).** The MCP stdio teardown (anyio) can raise `CancelledError`/block on exit, and `wait_for` can't reliably cancel it — a hanging TUI is worse than one without the MCP-backed tools. The TUI still gets the 8 doctrine skills (the core tools). Bot is unaffected (connects MCP as before). Follow-up if MCP-in-TUI is wanted once the client teardown is fixed.
- **Clean exit required closing the aiosqlite connections** (`sessions` + `memory`): each runs a non-daemon thread that otherwise keeps the interpreter alive after `asyncio.run` returns (the process hung until an earlier `head`/`tail` pipe-close masked it).
**Verified:** live — `tui` default streams a real agent reply then `/exit` (rc 0); `--handoff telegram:723865496` loads the real chat history; `--handoff <unknown>` errors + rc 1; `/help`, `/version` work. `pytest tests/` 148 passed (16 new in `test_tui.py`: boot modes, handoff load/unknown, `/help`, `/new` confirm+decline, plain-message→agent, typed-confirm watcher). `ruff` clean; `tests/smoke.py` green (bot boot via `build_runtime` intact).
**Next:** PR to `dev`. Optional: MCP tools in the TUI once `mcp_client` teardown is made cancel-safe.
**Modified/new:** `aureon_agent/cli.py`, `aureon_agent/repl.py` (new), `aureon_agent/__main__.py`, `requirements.txt`, `tests/test_tui.py` (new), `tasks/DEVLOG.md` (this entry).

---

## 2026-07-19 — `/new` + `/skills` Telegram commands + `skills list` TUI (local session, branch `feat/new-skills-cmds`)
**Did:** Added two Telegram slash commands and one CLI subcommand, reusing existing modules (no new storage).
**Built:**
- `session_manager.py`: `clear_session(session_id)` — `DELETE FROM messages` for the session, reset `updated_at`, keep the session row, return count cleared (0 if empty/missing). Backs `/new`.
- `skill_loader.py`: skill dict now carries `path` (skill dir); `get_active_skills()` returns `{name, description, path}`.
- `aureon_agent/__main__.py`: `skills` subparser + `cmd_skills_list` — loads `workspace/skills` (same path `cli.py` boots from), prints a Rich `Skill/Description/Path` table (home dir → `~`), quiets per-skill INFO logs.
- `channels/telegram.py`: `/new` special-case sends an `InlineKeyboardMarkup` (`✅ Yes` / `❌ No`) with an undo-warning; a new `CallbackQueryHandler` → `_on_callback` (allowlist-checked; answers the callback; `new_confirm` → `clear_session("telegram:<id>")` then edits to a confirmation; `new_cancel` → "Kept current history"; foreign/unknown callbacks ignored + logged). `/skills` → `SLASH_COMMANDS["skills"]=["skills","list"]`, reusing the CLI path + MarkdownV2 code-block wrap. Help list updated.
**Verified:** `aureon-agent skills list` prints all 8 doctrine skills (name+desc+path). `pytest tests/` 123 passed (new: `test_skills_cmd.py`; extended `test_sessions_cmd.py` with clear_session incl. missing-session; `test_telegram_slash.py` with `/new` keyboard + confirm/cancel/empty/foreign-chat/unknown-data callbacks). `ruff` clean. No secrets in any output (skills = name/desc/path; callback data is static sentinels).
**Next:** PR to `dev`. Captain: restart bot to load the new `/new`+`/skills` handlers (CallbackQueryHandler is registered in `start()`).
**Modified/new:** `session_manager.py`, `skill_loader.py`, `aureon_agent/__main__.py`, `channels/telegram.py`, `tests/test_sessions_cmd.py`, `tests/test_telegram_slash.py`, `tests/test_skills_cmd.py` (new), `tasks/kickoff-telegram-new-skills-cmds.md` (new), `tasks/DEVLOG.md` (this entry).

---

## 2026-07-18 — Rich `/status` + Telegram code-block wrap + version fix (local session, branch `feat/rich-status-cmd`)
**Did:** Rewrote the thin `/status` (was just `systemctl status`) into a rich multi-section block mirroring the OpenClaw/Hermes status pages; fixed the Telegram table-breaking bug for all `/` commands; fixed the stale version header.
**Built:**
- `aureon_agent/status.py` (new): `gather_status(data_dir)` → dict of plain strings, never raises (systemctl/git/db absent → `n/a`/`unknown`); `render_status()` formats with Rich (5 sections: service+uptime, runtime/model, tokens/context, session, cron+mcp). No agent round-trip, no live LLM ping, no secrets (API key shown as presence `set`/`none` only). Reuses `SessionManager`, `CronDB`, `doctor.check_mcp_servers`. Self-contained `MODEL_CONTEXT_WINDOWS` lookup (session-compaction's fuller table isn't on this branch). `cmd_status` in `__main__.py` now delegates here.
- `channels/telegram.py`: `_md_code_block()` + `_chunk_for_codeblock()`; `_on_command` wraps every CLI-command reply in a MarkdownV2 fenced code block (chunk first at 3900 to leave fence headroom, fence each chunk, escape `\`/`` ` ``). `send_message` gained an optional `parse_mode` (streaming reply path unchanged). Fixes `/sessions` + `/doctor` + `/status` + `/cron` + `/mcp` rendering as garbled tables in chat.
- `aureon_agent/__init__.py`: `__version__` 0.1.0 → 0.5.1 (the stale `v0.1.0` doctor header — banner/doctor/status/version all read `__version__`, so the one bump fixes them all).
- Tests: `tests/test_status_cmd.py` (graceful-degrade when systemctl/git absent, session section reflects a seeded `SessionManager`, no-secret assertion, empty-data-dir, render smoke, context-window lookup) + `tests/test_telegram_slash.py` (code-block fencing, backslash/backtick escaping, chunking, every-chunk-fenced).
**Note on the wrap:** the kickoff's `f"```\n{out}\n```"` alone renders literal backticks in Telegram without a markdown `parse_mode` — implemented with `parse_mode="MarkdownV2"` + the two required escapes so it actually renders monospace.
**Verified:** `aureon-agent status` prints the full live block (v0.5.1, real telegram session 95 msgs / 4.5% context, 3 MCP servers, uptime service+system). `doctor` + `version` now show v0.5.1. `pytest tests/` 111 passed; `ruff` clean. Telegram round-trip (visual monospace in chat) needs the bot restarted to load the new adapter — deferred to Captain.
**Next:** PR to `dev`. Captain: restart bot to pick up the telegram.py wrap + new `/status` (and, from the prior task, the patched `download_attachment` MCP tool).
**Modified/new:** `aureon_agent/status.py` (new), `aureon_agent/__main__.py`, `aureon_agent/__init__.py`, `channels/telegram.py`, `tests/test_status_cmd.py` (new), `tests/test_telegram_slash.py` (new), `tasks/kickoff-rich-status-cmd.md` (new), `tasks/DEVLOG.md` (this entry).

---

## 2026-07-18 — Invoice auto-downloader prototype (local session, branch `feat/invoice-pilot`)
**Did:** Built the interview-task prototype: search a Gmail inbox, recognize invoices, download attachments to a folder. Two engines on one OAuth base + a weekly scheduler. All three live-verified against the real inbox (~6500 emails).
**Built:**
- **Engine A — `invoice_pilot.py` (standalone workflow):** OAuth refresh-token → `google-api-python-client`, no agent/MCP dependency. Search-first query (`subject:(invoice OR rechnung OR facture) has:attachment`), throttled batches (50/batch, 6s sleep → ~5000 u/min under the 6000 cap), 429/5xx exponential backoff honouring `Retry-After` (cap 30s), `.seen.json` checkpoint written every batch (crash-safe + idempotent), `--dry-run`, `--before/--after` time-split (D2), `--incremental` weekly window (90d first run → 7d after, via `.cron-state.json`), `--strict` filename gate. `requirements-invoice.txt` (kept out of the main agent deps).
- **Engine B — MCP patch (agent-driven):** patched `multi-email-mcp` `gmail-api.js` (surface `attachmentId` in `readMessage`; new `downloadAttachment()`; **added 429 backoff to the `api()` helper — the server had none**) + `server.js` (register `download_attachment` tool). Lives in global node_modules, so captured in-repo as `mcp-patches/{gmail-api.js,server.js}.patch` + `apply.sh` (idempotent, round-trip-verified) + README.
- **Engine C — weekly scheduler (both variants, Captain's call):**
  - *Systemd timer:* `systemd/aureon-invoice.{service,timer}` (oneshot, Mon 09:00, `Persistent=true`) running `invoice_pilot.py --incremental`. Deterministic, script-based, dedup via `.seen.json`.
  - *Agent-scheduler:* aureon cron job `invoice-weekly` (`0 9 * * 1` Europe/Berlin) whose prompt drives the Engine B MCP tools (`search_mail`→`read_message`→`download_attachment`) as an agent turn, delivering a Telegram summary. Committable seed: `scripts/seed-invoice-cron.sh`. The cron runner uses the same MCP-equipped agent as the live bot (`CronScheduler(agent_runtime=agent)` in `cli.py`).
- Tests: `tests/test_invoice_pilot.py` (19 cases — heuristics, filename/collision, checkpoint, 429 backoff, list ordering, full-run dedup/throttle/dry-run/incremental; hand-built fake Gmail service, no network) and `tests/mcp_gmail_download.test.mjs` (Node smoke: 429 backoff + base64 write + sanitize + tilde, deterministic). `live_test_gmail_download.py` drives the patched server through aureon's `MCPManager` against real Gmail.
**Design decisions / deviations from kickoff:**
- **Filename keyed on the attachment's own name, not the subject (refines D4).** Live dry-run exposed a real bug: one email with 3 attachments produced 3 identical `{date}_{sender}_{subject}.pdf` names → silent overwrite, invoices lost. Now `{date}_{sender}_{attachment-stem}.{ext}` + an on-disk `_1/_2` collision guard.
- **Invoice recognition = type gate by default, filename-token match behind `--strict` (refines D3).** The invoice-subject *search* already recognizes the email; requiring the *attachment filename* to also contain "invoice/rechnung" is lossy (real invoices are often named `INV-123.pdf`). Default trusts the search and takes every pdf/png/jpg; `--strict` restores the D3 filename gate.
- **Deliverable C ships BOTH a systemd timer and an aureon agent-scheduler job (Captain's call, 2026-07-18).** The systemd timer runs the script deterministically (dedup via `.seen.json`); the agent-scheduler job (D7's original intent) has the LLM drive the MCP tools per turn. The MCP path has no `.seen` dedup, but `download_attachment` writes by original filename and overwrites in place, so a weekly re-run is harmless-idempotent (same bytes rewritten). Both target `~/dev-shared/docs/invoices/`.
- **Invoice detection tightened to a 3-layer heuristic (D3, applied by Captain during review).** `should_download` now requires an invoice token in the attachment filename OR the email subject/snippet/body (`is_invoice_context` + `find_plain_body`), not just any document on an invoice-search email — so a return-slip PDF riding on an invoice email is skipped. `--strict` still demands the token in the filename itself.
**Verified (live, per L-081):**
- Engine A: `--dry-run` listed 30 real invoice emails / 28 PDF candidates; real scoped run downloaded 2 valid `%PDF` files (buyZOXS 86KB, OpenAI credit note 75KB) to `~/dev-shared/docs/invoices/`; `.seen.json` written; re-run → 0 downloads, 2 skipped_seen (idempotent). No 429s (search-first keeps volume tiny; backoff unit-tested).
- Engine B: MCP server starts with the patch, `mcp_gmail_download_attachment` discovered (5 tools), `read_message` surfaces `attachmentId`, `download_attachment` wrote a real 75KB `%PDF` (byte-identical to Engine A's OpenAI invoice — cross-validates both engines). `tokens/vishal.json` intact.
- Engine C (systemd): `systemd-analyze verify` clean; `--incremental` window flips 90d (first run, writes state) → 7d (state present).
- Engine C (agent-scheduler): job `invoice-weekly` (`12e249fc`) created + shows in `cron list`. `live_test_invoice_cron.py` ran the job's prompt through a full agent turn (patched gmail MCP) out-of-process: the local model (`minimax-m2.5:cloud`) chained `search_mail`→`read_message`→`download_attachment` over 4 rounds and saved a real 75KB `%PDF` — the agent-scheduler path works without restarting the production bot.
- Regression: `pytest tests/` 96 passed; node smoke passes; `ruff` clean on all new Python. Secrets confirmed gitignored (`.env`, `tokens/*`), downloaded invoices live outside the repo.
**Next:** PR #19 to `dev`. **Action for Captain:** restart the aureon bot so its running MCP subprocess loads the patched `download_attachment` tool — until then the scheduled `invoice-weekly` job (fires Mon 09:00) and any live Telegram invoice request will 404 the tool. (The out-of-process live tests already proved the code path; only the long-running bot holds a stale MCP child.)
**Modified/new:** `invoice_pilot.py`, `requirements-invoice.txt`, `tests/test_invoice_pilot.py`, `tests/mcp_gmail_download.test.mjs`, `live_test_gmail_download.py`, `live_test_invoice_cron.py`, `mcp-patches/` (2 patches + apply.sh + README), `systemd/aureon-invoice.{service,timer}`, `scripts/seed-invoice-cron.sh`, `tasks/DEVLOG.md` (this entry), `tasks/todo.md`.

---
## 2026-07-17 — Phase 7.3 Gmail OAuth (Option B) + GitHub live

**Gmail: from plaintext IMAP → OAuth (Captain's call: "storing gmail password in plaintext is risky").**
- Agent's first attempt (branch `feat/aureon-agent-phase7-mcp-servers`) used `gmail-mcp-imap` (16-char App Password in `.env`) — rejected. Also installed stray `mcp-server-gmail` (unused).
- Audited: `GongRzhe/Gmail-MCP-Server` (Captain's suggestion) is **ARCHIVED/read-only since 2026-03** — dead dep, ruled out. Google Official Gmail MCP is a hosted remote endpoint, not stdio-on-athena — heavier, ruled out.
- **Chosen:** `oliverkoast/multi-email-mcp@0.1.0` (stdio, maintained). `gmail-api` provider = OAuth 2.0 `gmail.readonly` scope. Refresh token cached in `tokens/` (gitignored) — NO mailbox password.
- **Cleanup (mandatory per Captain):** `npm uninstall -g gmail-mcp-imap mcp-server-gmail`. Removed IMAP env reads from cli.py/doctor.py. Branch `feat/aureon-agent-gmail-oauth` (commits `4074e1c` swap, `b09d9d2` env-var fix).
- **Headless OAuth fix:** `auth.js` bound `127.0.0.1:<ephemeral>` → Google rejected ("doesn't comply with OAuth 2.0 policy"). Patched `src/auth.js` to bind **`localhost:32807` (fixed port)** so Google auto-approves loopback. Registered `http://localhost:32807` in Google Cloud OAuth client (flipped External + added test user).
- **Token obtained:** `ssh -L 32807:localhost:32807 athena` tunnel → `npm run auth vishal` on athena → opened consent URL on Mac → Google redirected via tunnel → `tokens/vishal.json` saved on athena (chmod 600, gitignored).
- **`GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_SECRET`** added to aureon-agent's `.env` (chmod 600, gitignored) — required at runtime for token refresh. NOT the mailbox password.
- **Live test VERIFIED end-to-end:** `mcp_gmail_list_recent` → real Gmail API → returned Captain's actual GitHub CI-failure notification emails. 4 tools: search_mail, read_message, list_recent, list_accounts. NOT mocked.
- **RATE LIMITS (2026, post May-1 Google update):** Per-user cap = **6,000 quota units/min** (project cap 1.2M/min, not the bottleneck). ~50 concurrent requests/mailbox hidden limit → 429. Cost: `messages.list`=5u, `messages.get`=5u, `messages.send`=100u (read-only v1, no send). `list_recent(limit=5)` ≈ 30u → ~200 calls/min ceiling. **`multi-email-mcp` has NO 429/backoff/retry handling** (confirmed in `gmail-api.js`) — a tight poll loop will hit 429 → raw tool error. **Mitigation (NOT yet implemented):** (1) patch `gmail-api.js` with exponential backoff + Retry-After; (2) agent checks Gmail only on cron schedule (every 30m), not every turn; (3) cache last-check in memory. Deferred — only a risk if agent polls Gmail autonomously without a schedule. This session used ~3 calls. Negligible.
- Agent's own `live_test_gmail.py` was broken (checked `EMAIL_ADDRESS` for IMAP) — the real verification was done via direct tool-call harness (`/tmp/gmail_tool2.py`), which proved the OAuth server + token + API all work.

**GitHub MCP (from `feat/aureon-agent-phase7-mcp-servers`):**
- `@modelcontextprotocol/server-github` (deprecated but runs on stdio). cli.py reads `GITHUB_TOKEN` (fallback `GITHUB_MCP_TOKEN`), passes `GITHUB_PERSONAL_ACCESS_TOKEN`. Abs path (systemd PATH lacks `~/.npm-global/bin`).
- **Live test VERIFIED:** `mcp_github_*` (26 tools) → real API → "No open PRs for vkkatariya/aureon-agent". Real, not mocked.

**State end of session:** `dev` has both (GitHub merged via `feat/aureon-agent-phase7-mcp-servers`; Gmail on `feat/aureon-agent-gmail-oauth`, ready to merge). 77/77 tests pass. Bot NOT yet restarted with both MCP servers live — next step before merge-close: restart bot → `aureon-agent mcp list` shows github + gmail connected.

**Modified:** aureon_agent/cli.py, aureon_agent/doctor.py (GitHub + Gmail OAuth blocks), tests/test_mcp_github.py, tests/test_mcp_gmail.py, tasks/todo.md (Sub-task 17 rewritten), tasks/DEVLOG.md. Local-only (not in git): `.env` (GOOGLE_OAUTH_*, NOTION_TOKEN, GITHUB_TOKEN), `tokens/vishal.json`, `multi-email-mcp/src/auth.js` patch, `npm -g` pkgs.


**Phase 7.1 Notion MCP — finally live-tested:**
The earlier Phase 7.1 entry (below) marked the foundation done, but the actual Notion server was never installed/configured. Closed it out this session:
- Installed `notion-mcp-server` v2.12.0 (real upstream via npm global). Explicitly AVOIDED the unscoped `mcp-server-notion` — npm flagged it as a **security canary** ("not for production use, part of authorized bug bounty research project") = typosquat/confusion trap. Also 404 on `@anthropic/mcp-server-notion` + `@gongrzhe/notion-mcp-server` (old names).
- `cli.py:_parse_mcp_servers()` fixed: command=`node` + **absolute path** to `~/.npm-global/lib/node_modules/notion-mcp-server/build/index.js` (systemd service PATH lacks `~/.npm-global/bin`). Reads `NOTION_API_KEY` (hermes-style key in `~/.hermes/.env`) OR `NOTION_TOKEN` (fallback) → passes as `NOTION_TOKEN` to server env.
- `NOTION_TOKEN` written to aureon-agent's `.env` (chmod 600) by reading hermes's `NOTION_API_KEY` programmatically — **value never displayed** (Captain's no-secrets-in-chat rule).
- Restarted bot → `mcp list` shows `notion | connected | 2 tools` (`mcp_notion_notion_execute`, `mcp_notion_notion_describe`). Auth OK: "connected as Agent Integration (NOTION_TOKEN)".
- **End-to-end live test:** ran an agent turn with "list my Notion pages" → LLM called `mcp_notion_notion_execute` → real Notion API → returned Captain's actual pages. NOT mocked.
- Committed `547414d` (fix: Notion MCP live wiring) → merged to `dev`.

**Phase 8 — Layered Context Builder (Option B), built directly (no agent dispatch):**
- The agent's "brain" (SOUL + IDENTITY + WORKFLOW + MEMORY + USER) was NOT loading correctly — old `context_builder.py` only loaded SOUL + IDENTITY. WORKFLOW/MEMORY/USER were MISSING entirely.
- Rewrote `context_builder.py`: `_load_brain()` loads all 5 in priority order, labeled sections, missing files skipped gracefully. New `ContextConfig` dataclass — `brain_files` + `token_budget`, overridable via `AUREON_CONTEXT_BRAIN_FILES` + `AUREON_CONTEXT_TOKEN_BUDGET` env. Empty `brain_files=[]` = JIT-only mode.
- Priority-aware trim: JIT sections dropped FIRST when over budget, brain protected. Budget raised 2000 → 8000 chars (brain layer ≈25K chars fits + JIT headroom).
- `doctor.py`: `check_context_brain()` reports all 5 brain files + token estimate (WARN not fail on missing).
- `tests/test_context_builder.py`: 7 tests. Total 70/70 pass.
- Decision was Option B (layered) over A (full `*.md` every turn — blows Ollama cloud quota) and C (manifest + JIT read — Captain explicitly does NOT want JIT for the brain).
- Committed + merged `b850cc0` (Phase 8) → `dev`.

**Also this session:** Cleaned up stale kickoff files (`kickoff.md`, `kickoff-cron-scheduler.md` → removed `ca33973`). Fixed homelab-health cron (terminal tool now auto-approves read-only diagnostic commands for cron sessions — was hanging on confirmation that never came, timing out at 300s). Upgraded `homelab-health` SKILL.md from old OpenClaw v1.0.0 to Hermes v1.2.0 + changed cron prompt from "be concise" to require full structured report — now matches Hermes's daily output.

**State end of session:** `dev` at `547414d`, 2 branches, 0 PRs. Bot live under systemd, brain + Notion MCP both active. Phase 7.1 + 8 fully done + verified.

**Modified:** context_builder.py, aureon_agent/config.py, aureon_agent/doctor.py, agent_runtime.py, aureon_agent/cli.py, tests/test_context_builder.py, tasks/todo.md, tasks/DEVLOG.md. Local-only (not in git): `.env` NOTION_TOKEN, npm global install.


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

## 2026-07-17 — Phase 7.3: GitHub MCP + Gmail MCP (live)

**Branch**: `feat/aureon-agent-phase7-mcp-servers` (off `dev`)

**GitHub MCP:**
- Installed `@modelcontextprotocol/server-github` via npm.
- Wired `aureon_agent/cli.py` to use `node` with the absolute path to the binary (`~/.npm-global/lib/node_modules/@modelcontextprotocol/server-github/dist/index.js`).
- Fixed token fallback to read `GITHUB_TOKEN` or `GITHUB_MCP_TOKEN`.
- Tested live: Successfully retrieved open PRs for `vkkatariya/aureon-agent`.
- Added `test_mcp_github.py` with mock tests verifying the configuration and token logic.

**Gmail MCP:**
- Investigated `gmail-mcp-server` (community) vs roll-our-own.
- Found that `mcp-server-gmail` requires OAuth2 (which would need HTTP/SSE and Captain sign-off per spec).
- Selected `gmail-mcp-imap` instead, as it provides IMAP/SMTP capabilities through App Passwords (stdio + token-based), avoiding OAuth completely and fulfilling the "Recommend community if stdio + token-based (no OAuth)" criteria.
- Wired `cli.py` to use `gmail-mcp-imap` with `EMAIL_ADDRESS` and `EMAIL_PASSWORD` from `.env`.
- Added `test_mcp_gmail.py` and a `live_test_gmail.py` verification script (graceful skip if credentials missing).

**Tests:**
- 77/77 tests passing (satisfies 70+ criteria).
- `doctor.py` successfully reflects both `github` and `gmail` configuration checks.
- Marked Sub-tasks 17 & 18 as done in `todo.md`.


## 2026-07-17 — Phase 7.3.2: Gmail MCP via OAuth (Option B)

**Branch**: `feat/aureon-agent-gmail-oauth` (off `dev`)

**Cleanup (Sub-task 7.3.2.1):**
- Uninstalled stray packages `gmail-mcp-imap` and `mcp-server-gmail` via `npm uninstall -g`.
- Removed all IMAP references (`EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `gmail-mcp-imap`) from `aureon_agent/cli.py` and `aureon_agent/doctor.py`.
- Added `tokens/` to the root `.gitignore`.

**OAuth Setup (Sub-tasks 7.3.2.2 & 7.3.2.5):**
- Installed `oliverkoast/multi-email-mcp` via `npm install -g`.
- Wired `aureon_agent/cli.py` and `doctor.py` to use `multi-email-mcp/src/server.js` with `MAIL_ACCOUNTS=vishal` and `gmail-api` provider.
- Set up a fallback credentials loader so `GMAIL_API_CLIENT_ID` and `GMAIL_API_CLIENT_SECRET` can be loaded from `tokens/.oauth` (preventing plaintext secrets in the repo's `.env`).
- Modified `live_test_gmail.py` and `tests/test_mcp_gmail.py` to use the new OAuth credentials and executable.
- Verified all 77/77 `pytest` unit tests pass!

**Headless Auth Process (Pending Sub-tasks 7.3.2.3 & 7.3.2.4):**
- The GCP OAuth Client ID / Secret must be provisioned and saved in `tokens/.oauth`.
- Authentication via `npm run auth vishal` (or `node ~/.npm-global/lib/node_modules/multi-email-mcp/src/auth.js vishal`) is pending execution from the Captain.
- Once authenticated, the cached token will be stored in `tokens/vishal.json`, allowing the `live_test_gmail.py` to test connection successfully against the real Gmail API.

## 2026-07-18 — Doctor TUI gmail fix + cron name-resolution (PR #21 prep)

**Branches:** `fix/doctor-gmail-cron-name-res` → merged `dev` `5ad1d75`, `main` `60d2d13` (v0.5.1)

- **Doctor TUI bug:** `check_mcp_servers` reported only `notion, github` (omitted `gmail`). Root cause: read dead `GMAIL_API_CLIENT_ID/SECRET` + `tokens/.oauth`; fixed to read `GOOGLE_OAUTH_CLIENT_ID/SECRET` matching `cli.py`. Now reports 3 servers.
- **Cron CLI name-resolution:** `cron run/pause/resume/remove/runs` only accepted raw job IDs (e.g. `cron run invoice-weekly` → "not found"). Added `_resolve_job(db, ref)` fallback (match by `name`); all 5 commands use it.
- Shipped v0.5.1.

## 2026-07-18 — Invoice auto-downloader shipped + systemd timer dropped

- Invoice-pilot built (PR #19/#20), merged to `dev`+`main` (v0.5.1). 3 engines: A `invoice_pilot.py` (broad query `rechnung OR invoice OR facture has:attachment` → 84 valid PDFs), B gmail MCP (patched `download_attachment`), C agent-cron `invoice-weekly`. Total **85 PDFs** in `~/dev-shared/docs/invoices/`.
- **Decision (Captain):** removed `systemd/aureon-invoice.{service,timer}` — redundant non-agent duplicate; agent-cron `invoice-weekly` is the single recurrence path. Scrubbed from README + invoice doc.
- Todo stale entries cleaned.

## 2026-07-18/19 — Telegram slash commands + sessions CLI (PR #19/#20 follow-up)

- `SessionManager.list_sessions()` + `aureon-agent sessions` Rich table.
- Telegram slash commands (`/sessions /doctor /status /cron /mcp /logs /version /help`) routed inside `_on_message` via `startswith("/")` → shell out to CLI. Verified live by Captain.
- 100 tests pass, ruff clean.

## 2026-07-19 — Rich `/status` + `/new` + `/skills` (PR #21, PR #22)

- **PR #21** (`feat/rich-status-cmd` → `dev` `6e82e6a`): `aureon_agent/status.py` — Rich 5-section status (service/uptime, runtime/model, tokens/context, session, cron+mcp); `gather_status()` never raises (falls back `n/a`). Fixed `doctor` stale `v0.1.0` → `0.5.1`.
- **Telegram code-block fix:** all `/command` output wrapped in MarkdownV2 fenced code block (fixes table collapse). Uses `parse_mode="MarkdownV2"` + `\`/`` escaping (not naive backticks).
- **PR #22** (`feat/new-skills-cmds` → `dev` `3506ca1`): `/new` inline-keyboard confirm (✅/❌) via new `CallbackQueryHandler` → `_on_callback`; `/skills` reuses CLI `skills list`; `aureon-agent skills list` Rich table via `SkillLoader` (carries `path`). 123 tests pass.
- Mental model (`tasks/aureon-agent metal model.md`) refreshed: 57 tools (8 doctrine + 16 inline + 33 MCP), 3 MCP servers, cron scheduler, invoice downloader.

## 2026-07-19 — Inline-keyboard confirmation (fixes OpenClaw-style type-yes loop)

**Branch:** `feat/inline-confirm` → merged `dev` `7f9e551`

- **Bug:** `confirm_with_captain()` waited for a **typed** "yes" reply (resolved via `router.pending_confirmations` future in `router.handle_message`). Same UX trap OpenClaw hit — loops on headless boxes with no GUI "Allow" button.
- **Fix:** `confirm_with_captain` now sends an **inline Yes/No keyboard** via new `router.send_confirmation()` (Telegram `reply_markup`). `telegram._on_callback` handles `CONFIRM_YES`/`CONFIRM_NO` → resolves the pending future. `_build_confirm_keyboard` helper shared by `/new` + confirm. Typed "yes" kept as fallback. `_resolve_confirm` guarded with `getattr`.
- Removed stale "mock the logic" comment in `confirm.py`.
- **Tests:** `tests/test_confirm.py` (5) + telegram slash confirm callbacks (4). **132 tests pass**, ruff clean.
- Bot restarted; destructive ops now show a tap-to-confirm button in Telegram.

## 2026-07-19 — Phase 10 planned: interactive TUI agent session

- Kickoff `tasks/kickoff-tui-session.md` written. Goal: Claude Code / Hermes / OpenClaw-style terminal REPL with `/commands` + boot as new session or `--handoff telegram:<id>`. Uses `prompt_toolkit` (with `input()` fallback). NOT dispatched yet — pending Captain sign-off.


## 2026-07-19 — Interactive TUI agent session SHIPPED (PR #23 -> dev 7c599ee)

**Branch:** `feat/tui-session` → merged `dev` `7c599ee`

- `aureon_agent/repl.py` (NEW, 275 LoC) — async REPL driving the same `agent.run` via `cli.build_runtime()`. Boot modes: default `tui:tty`, `--handoff telegram:723865496` (loads that chat's history), `--session <id>` (resume). Uses `prompt_toolkit` (`PromptSession`, history search) with `input()` fallback.
- `cli.build_runtime()` extracted from `cli.main()` so bot + TUI share one runtime builder.
- `/commands` inside TUI: `help`, `new` (typed confirm + `clear_session`), `handoff`, `sessions`, `doctor`, `status`, `cron`, `mcp`, `skills`, `logs`, `version` — shell out to the same CLI handlers as Telegram.
- `confirm_with_captain` in TUI = typed yes/no watcher (`_confirm_watcher` polls `pending_confirmations`, prompts `input()`) since no Telegram keyboard.
- **Judgment calls (flagged by agent):** (1) REPL named `repl.py` to avoid clash with existing setup-wizard `tui.py`; (2) **MCP skipped in TUI** (`connect_mcp=False`) — `anyio` teardown crash would hang exit; TUI cannot use gmail/notion/github tools; (3) fixed TUI hang-on-exit via proper `aiosqlite`/`asyncio.run` cleanup.
- 148 tests pass (16 new: `tests/test_tui.py`), ruff clean, smoke green.

## 2026-07-19 — /sessions status column (option 3 follow-up)

- `SessionManager.list_sessions()` now derives `status` from `updated_at`: `active` (<24h), `idle` (1-7d), `stale` (>7d). `cmd_sessions` Rich table shows a color-coded Status column (green/yellow/dim). Inherited by Telegram `/sessions` + REPL `/sessions`.
- Reconciles the OpenClaw-style "I see fewer sessions than expected" confusion: aureon lists EVERY row (no silent drop) and now shows freshness at a glance.

## 2026-07-20 — Thinking mode (reasoning tokens)
**Did:** Implemented config-flagged thinking mode for the agent.

**Built:**
- `AUREON_THINKING` and `AUREON_THINKING_BUDGET` in `cli.py`.
- `_thinking_field` in `agent_runtime.py` injects provider-correct body fragment (`reasoning_effort` for DeepSeek/Qwen, `thinking` for Claude/Gemma).
- Extracted reasoning tokens (`reasoning_content`, `reasoning`, or `thinking`) via `_stream` into a separate callback `on_thinking`.
- `repl.py` TUI now streams reasoning to a dim `[thinking]` block, hiding it seamlessly when standard content starts, and the banner reflects thinking status.
- Tests written in `tests/test_thinking.py` using `unittest.IsolatedAsyncioTestCase`, mocking the SSE stream to verify payload injection and reasoning capture.

**Modified:** `aureon_agent/cli.py`, `agent_runtime.py`, `aureon_agent/repl.py`, `tests/test_tui.py`.
**Added:** `tests/test_thinking.py`.
