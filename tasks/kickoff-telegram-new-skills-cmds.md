# Kickoff: `/new` + `/skills` Telegram commands + `aureon-agent skills list` TUI

**Context:** Captain wants two new Telegram slash commands and one new CLI subcommand:
1. `/new` — start a new session, with a **confirmation popup** (inline keyboard) before wiping history.
2. `/skills` — list the loaded doctrine skills.
3. `aureon-agent skills list` — TUI equivalent of `/skills`.

**Current state (verified):**
- Slash commands routed in `channels/telegram.py:_on_command` via `SLASH_COMMANDS` dict → shells out to CLI (`subprocess.run([... "aureon_agent.__main__", *args])`), output wrapped in MarkdownV2 code block. `help` is special-cased.
- Session storage: `session_manager.SessionManager` — one linear thread per `channel:chat_id` (`get_or_create_session(client_id, channel)` → `f"{channel}:{client_id}"`). `messages` table keyed by session_id. **No multi-session-per-chat.** So "new session" = **reset the current chat's history**.
- Skills: `skill_loader.SkillLoader` (loaded in `cli.py` at boot) → `get_active_skills()` returns list of loaded skill dicts (name, description, etc.). 8 doctrine skills from `workspace/skills/`.
- TUI subcommands registered in `aureon_agent/__main__.py` via `subparsers.add_parser(...)`. Existing pattern: `sessions`, `mcp list`, `cron <sub>`, `doctor`, `status`, `version`, `tool-log`, etc.

**Goal:** Add the 3 surfaces reusing existing modules. No new storage format. No LLM round-trip for these (they're operator commands).

---

## Deliverable 1 — `/new` (new session + confirmation inline keyboard)

**Behavior:**
1. Captain sends `/new`.
2. Bot replies with an **inline keyboard** (Telegram `InlineKeyboardButton`): `[✅ Yes, start new] [❌ No, keep]` + a warning: "This clears the current chat history (telegram:723865496). Cannot be undone."
3. Captain taps **Yes** → bot calls `SessionManager` to **delete all messages** for the current session_id, then confirms "✅ New session started." Tapping **No** (or timeout) → "Kept current history."

**Why inline keyboard (not free-text):**
- "Confirmation popup" = Telegram inline keyboard — the native confirm UI. Avoids parsing "yes/no" text + ambiguous replies.
- Requires handling `CallbackQuery` updates → add a `CallbackQueryHandler` in `telegram.py:start()`, routed to `_on_callback`.

**Implementation:**
- `SessionManager`: add `async def clear_session(session_id)` — `DELETE FROM messages WHERE session_id = ?` + reset `updated_at` (or delete the sessions row so `get_or_create` re-creates clean). Simplest: delete messages rows for that session_id; leave the sessions row (updated_at reset). Degrade gracefully if session missing.
- `telegram.py`:
  - `start()`: add `Application.builder()...build()` then `self._app.add_handler(CallbackQueryHandler(self._on_callback))` (after the MessageHandler).
  - `_on_command`: add `"new": None` sentinel to `SLASH_COMMANDS` (or special-case like `help`) → send confirmation with inline keyboard via `self._app.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(...))`.
  - `_on_callback(update, _context)`: read `callback_query.data` (`"new_confirm"` / `"new_cancel"`), answer the callback (`answer_callback_query`), then on confirm → `await sm.clear_session(f"telegram:{chat_id}")` → edit the message to the confirmation text.
- **Safety:** only act if `chat_id in self.allowed_chats`. Use a stable `callback_data` string (max 64 bytes). No secrets in callback data.
- **No LLM:** `/new` confirmation is pure bot logic.

**Edge cases:** callback from a non-allowed chat → ignore. Callback with unknown data → log + ignore. Session already empty → "already fresh."

## Deliverable 2 — `/skills` (Telegram)

- Add `"skills": ["skills", "list"]` to `SLASH_COMMANDS` (reuses the existing CLI `skills list` path — same as `/mcp`/`/cron` pattern).
- Output: the CLI `skills list` prints a Rich table of active skills (name + description). `_on_command` already wraps CLI output in a MarkdownV2 code block → renders aligned in chat.
- No special handling needed beyond the `SLASH_COMMANDS` entry + ensuring `skills list` CLI exists (Deliverable 3 builds it).

## Deliverable 3 — `aureon-agent skills list` (TUI)

- `aureon_agent/__main__.py`: add `skills` subparser with `list` subcommand → `cmd_skills_list(args)`.
- `cmd_skills_list`: load `SkillLoader(workspace/skills dir)`, call `get_active_skills()`, print a Rich table (columns: Skill, Description, Path). Reuse the existing Rich import pattern from `cmd_mcp_list`/`cmd_sessions`.
- The skills dir: resolve same way `cli.py` does (symlinked `workspace/skills/` → `~/.openclaw/workspace/skills/`). Read from the same path `cli.py` uses so output matches the running bot's loaded skills.
- Add dispatch branch in `main()`: `elif args.command == "skills": cmd_skills_list(args)` (handle `skills list`).

---

## Constraints
- **No `0.0.0.0` binds**, localhost/Tailscale only (N/A here, but keep callbacks server-side).
- **Secrets never printed** — skills list shows name/description/path only.
- **Reuse, don't duplicate:** `SessionManager` (add `clear_session`), `SkillLoader` (existing), `cmd_*` Rich pattern, `_on_command` code-block wrap.
- **Code-block wrap** for `/skills` output (consistency with `/sessions`/`/doctor`/`/status`).
- **Inline keyboard** for `/new` is the only new Telegram handler type (CallbackQuery) — keep it minimal + allowlist-checked.
- **Caveman mode** applies to bot replies (per SOUL.md).

## Tests
- `tests/test_sessions_cmd.py`: add `test_clear_session` — seed messages, clear, assert empty; clear missing session → no error.
- `tests/test_telegram_slash.py`: add `/skills` routes to CLI `skills list`; `/new` sends an inline-keyboard message (mock `send_message` capture `reply_markup`).
- `tests/test_skills_cmd.py` (new): `cmd_skills_list` prints all 8 doctrine skills from a temp skills dir.

## Verification
- `python -m pytest tests/ -q` green.
- `aureon-agent skills list` prints the 8 skills (name + description + path) in a Rich table.
- Restart bot; `/skills` from Telegram → aligned code-block list.
- `/new` from Telegram → inline keyboard appears; tap Yes → history cleared (verify `data/sessions.db` messages count drops); tap No → unchanged.
- `ruff` clean.

## Suggested commits
- `feat(session): add clear_session() to SessionManager`
- `feat(telegram): /new with inline-keyboard confirmation + CallbackQuery handler`
- `feat(telegram): /skills slash command (reuses CLI skills list)`
- `feat(cli): aureon-agent skills list subcommand (Rich table via SkillLoader)`
- `test: skills_cmd + clear_session + /new /skills telegram tests`
