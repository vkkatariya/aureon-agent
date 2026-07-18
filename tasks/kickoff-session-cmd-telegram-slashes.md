# Kickoff: session listing + Telegram slash commands

**Goal:** (1) a `sessions` CLI command to list all chat sessions from `sessions.db`; (2) Telegram `/slash` commands for the existing CLI surface so Captain can self-serve health/status without SSH.

**Scope (per Captain):** commands to see all sessions + telegram slash commands for all the commands we have.

## Deliverables

### A. `sessions` CLI command
- `session_manager.py`: add `async def list_sessions() -> list[dict]` — `SELECT session_id, channel, client_id, COUNT(messages.idx) AS msg_count, updated_at FROM sessions LEFT JOIN messages ... GROUP BY session_id ORDER BY updated_at DESC`. Returns dicts.
- `aureon_agent/__main__.py`: add `sessions` subcommand → opens SessionManager, calls `list_sessions()`, prints a Rich table (session_id, channel, client_id, msgs, last active). Reuse existing Rich import pattern from cron_cli.

### B. Telegram slash commands
- `channels/telegram.py`: add `CommandHandler` (python-telegram-bot) for a set of commands, routed in `_on_command`. Commands map to existing logic:
  - `/sessions` → list_sessions() formatted
  - `/doctor` → run `check_*` from doctor.py, return pass/warn/fail lines
  - `/status` → systemd service status (subprocess `systemctl --user status aureon-agent.service` or equivalent)
  - `/mcp` → `aureon-agent mcp list` output
  - `/cron` → `cron list` table
  - `/logs` → tail last ~20 lines of journalctl (or `aureon-agent logs`)
  - `/version` → version string
  - `/help` → list available slash commands
- Allowlist enforced (only allowed_chats). Commands MUST NOT require SSH.
- Responses chunked to 4096 (reuse TELEGRAM_MAX_LEN + chunk helper).
- Doctor/status/mcp/cron/logs reuse the SAME functions the CLI uses (no duplication) — import from `aureon_agent.doctor`, `cron_cli`, etc. Keep it thin: slash handler builds the args object and calls the existing `_cmd_*` / `cmd_cron` with a fake args namespace.

## Constraints
- No `0.0.0.0` binds. Telegram only (Captain's chat allowlist).
- Secrets never printed (doctor already redacts).
- Keep session arch unchanged (one linear thread per channel:chat_id). Slash commands are NEW surface, not a new session type.
- Small focused commits: `feat(session): add list_sessions + CLI command`; `feat(telegram): add slash commands for CLI surface`.

## Verification
- `python -m pytest tests/ -q` green.
- `aureon-agent sessions` prints the real sessions from `data/sessions.db` (should show `telegram:723865496` + cron:* rows).
- Restart bot; send `/sessions`, `/doctor`, `/help` from Telegram → get real output.
- `tests/test_sessions_cmd.py`: list_sessions returns expected rows for a temp DB; CLI sessions command prints a table.

## Out of scope
- No new session *type* (cron/subagent stay isolated as-is).
- No webhook (separate todo item).
- No group/server channels (separate todo item).
