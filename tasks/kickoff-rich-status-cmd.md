# Kickoff: rich `/status` command (OpenClaw/Hermes-style)

**Context:** Captain sent screenshots of two status pages he likes:
1. **OpenClaw** `/status` — version+commit, current time (local + UTC), uptime (gateway/system), active model + key + fallback chain + primary, token in/out + cost, context used/total + compactions, session id + duration + updated, rich-message flag, execution mode/runtime/think/fast, queue state.
2. **Hermes TUI** `/status` — session id, path, title, model+provider, created, last activity, tokens, agent running (Yes/No).

**Current aureon `/status`:** `cmd_status()` in `aureon_agent/__main__.py:67` only shells `systemctl --user status aureon-agent.service --no-pager`. Thin, not agent-aware. Want it to match the richness of those two references — a single self-contained status block covering: service health, runtime/model, session, tokens/context, cron, MCP.

**Goal:** Rewrite `cmd_status()` to emit a rich, multi-section status (Rich-formatted) covering the dimensions below. No agent round-trip needed — gather from local state + lightweight probes. Keep it fast (<2s), no secrets printed.

## Required fix: Telegram code-block wrapping for ALL `/` commands

**Problem (observed in screenshots):** The `/sessions` and `/doctor` outputs render as Rich tables in the terminal (box-drawing chars `┏━┓`, aligned columns) but **break in Telegram** — Telegram strips/garbles Rich's box characters and monospace alignment outside a code block, so the table structure collapses (see the `Chat Sessions` + `Aureon Agent Health` screenshots Captain sent: columns misalign, rows scramble).

**Fix:** Every `/` command's output, when delivered to Telegram, MUST be wrapped in a fenced code block so Telegram renders it monospace:

```
out = f"```\n{out.strip()}\n```"
```

Apply this uniformly in `channels/telegram.py` `_on_command` (the single delivery point) — one change covers `/sessions`, `/doctor`, `/status` (new), `/cron`, `/mcp`, `/logs`. Do NOT rely on `channels.telegram.richMessages`; a plain ```code block``` is the minimal, reliable fix and works today.

**Scope of this fix (spans existing + new commands):**
- Existing: `/sessions` (table breaks), `/doctor` (table breaks), `/cron`, `/mcp` — all currently shell out to the CLI and send raw Rich stdout → wrap in code block.
- New: `/status` (this kickoff) — emit Rich for CLI, but the Telegram path already wraps via the shared `_on_command` code-block rule, so no special-casing needed.
- Note: the `Aureon Agent Health` screenshot also shows a **stale `v0.1.0`** header — `doctor` is printing a hardcoded/old version string. While fixing, make `doctor` pull the real version from `aureon_agent.__version__` (same source `/status` will use) instead of a literal. Capture that as part of the doctor touch-up.

**CLI (terminal) behavior unchanged:** `aureon-agent sessions|doctor|status` in a real terminal keeps the pretty Rich tables. Only the Telegram delivery path gets the code-block wrap.

## Required sections (map to the screenshots)

### A. Service / uptime
- `aureon-agent <version> (<commit>)` — version from `aureon_agent.__version__`; commit from `git rev-parse --short HEAD` (best-effort, fall back to "unknown").
- `Current time: <local, e.g. Saturday, July 18th, 2026 - 10:28 PM (Europe/Berlin)>` — `datetime.now()` + `ZoneInfo(os.getenv("TZ","Europe/Berlin"))`; also `Reference UTC: <YYYY-MM-DD HH:MM UTC>`.
- `Uptime: service <X> · system <Y>` — service start = `systemctl show aureon-agent.service -p ActiveEnterTimestamp` (or parse `systemctl status`); system boot = `uptime -s` or `/proc/stat btime`. Compute human durations.
- `Status: active (running) / inactive / failed` — `systemctl is-active`.

### B. Runtime / model
- `Model: <active model> · key <...> · auto fallback` — active model = the LLM the agent currently uses. Pull from `agent_runtime` config (the configured primary model + provider). If a live call is too heavy, read the configured model string from config/env (e.g. `OPENAI_MODEL` / provider config) — document the source.
- `Fallbacks: <list>` — the fallback model list from config.
- `Execution: direct · Runtime: <name> · Think: off · Fast: off` — mirror OpenClaw's execution/runtime/think/fast flags. Source from agent config (think/fast may be config bools; default off).

### C. Tokens / context
- `Tokens: <in> in / <out> out · Cost: $<x>` — if the agent tracks token usage in a log/db, read it; else show session-history token estimate from `SessionManager.get_history` (sum of len(content) / 4) as a rough "<~Nk context>". Be honest about estimate vs measured.
- `Context: <used>/<total> (<pct>%) · Compactions: <n>` — total = model context window (config); used = current session token estimate; compactions = count from session/compaction log if tracked, else 0.

### D. Session
- `Session: <session_id> · duration <Xs> · updated <when>` — the active chat session. From `SessionManager.list_sessions()` pick the most-recently-updated (the Captain's telegram chat). Show `channel:client_id`, msg count, last active.
- `Agent Running: Yes/No` — whether the bot process is active (systemctl is-active) + scheduler running.

### E. Cron + MCP (aureon-specific, adds value over the refs)
- `Cron: <n> jobs (<m> enabled, <k> due soon)` — from `cron.py`/`cron_db` `list_jobs()`.
- `MCP: <server> ✅<n tools> ...` — reuse `doctor.check_mcp_servers()` result (already returns the 3-server summary).

## Constraints
- **No secrets:** never print API keys/tokens/refresh_tokens. Show key *presence* only (e.g. `key: set` / `oauth: ok`).
- **Fast + offline-tolerant:** if `systemctl`/git unavailable (headless), degrade gracefully (show "n/a") — don't crash.
- **Reuse, don't duplicate:** pull from `SessionManager`, `doctor.check_mcp_servers`, `cron` db, `agent_runtime` config. Same data the other commands use.
- **Rich output:** use `rich.console.Console` + `rich.table.Table` / `rich.panel.Panel` to match the clean look of the references. CLI keeps pretty tables.
- **Telegram code-block wrap (required):** all `/` command output is wrapped in a ``` fenced block at the single `_on_command` delivery point (see "Required fix" above). This fixes the broken table rendering in chat.
- **Single command:** `aureon-agent status` (CLI) + `/status` (Telegram) both call the new `cmd_status`.

## Out of scope
- Full rich Telegram markdown rendering (`channels.telegram.richMessages`) — we use plain ```code blocks``` instead (reliable today, no new setting).
- Webhook mode (separate todo item).
- Live LLM ping to detect "active model" — use configured model, not a round-trip.

## Verification
- `aureon-agent status` prints the full block (service + runtime + tokens + session + cron + mcp) against the live box.
- `tests/test_status_cmd.py`: (1) `cmd_status` runs without raising when systemctl absent (monkeypatch `subprocess` to raise → graceful "n/a"); (2) session section reflects a seeded `SessionManager` row; (3) no secret strings appear in output.
- `tests/test_telegram_slash.py` (or extend existing): `_on_command` wraps output in ```code block``` for every command (assert returned text starts/ends with ```).
- Restart bot; `/status`, `/sessions`, `/doctor` from Telegram all render as aligned monospace code blocks (no broken tables).
- `ruff` clean, `pytest` green.

## Suggested commits
- `fix(telegram): wrap all /command output in code block (fixes broken Rich tables in chat)`
- `fix(doctor): use real version from __version__ instead of hardcoded v0.1.0`
- `feat(status): rich /status block (service, runtime, tokens, session, cron, mcp) mirroring OpenClaw/Hermes`
- `test(status): status_cmd graceful-degrade + no-secret + session-section tests`
- `test(telegram): /command code-block wrapping test`
