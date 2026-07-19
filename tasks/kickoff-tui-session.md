# Kickoff: interactive TUI agent session (Claude Code / Hermes / OpenClaw style)

**Context:** Captain wants an **interactive terminal UI** for aureon-agent — like `claude-code`, `hermes`, `openclaw` — that you run in a terminal and chat with the agent live. Inside it: all the `/commands` (sessions, doctor, status, cron, mcp, skills, logs, version, help, new) and it **boots either as a new session or by `/handoff`-ing an existing Telegram session** (load that chat's history so the terminal continues the conversation).

**Current state (verified):**
- `agent_runtime.run(history, session_id, callbacks)` is **channel-agnostic** — Telegram calls it via `router.handle_message("telegram", chat_id, text, {on_token, on_tool_use})`. A TUI just needs its own channel/loop feeding the same `run`.
- `SessionManager` (`session_manager.py`): `get_or_create_session(client_id, channel)`, `get_history(session_id)`, `add_message`, `clear_session`, `list_sessions`. Sessions keyed by `channel:client_id`. So a TUI session = channel `"tui"`, client_id = e.g. `tty` or a generated id; a handoff = reuse `telegram:723865496`'s history.
- `ChannelRouter` (`channels/router.py`): owns `sessions`, `pending_confirmations`, dispatches `handle_message`. Built for async channels. A TUI can either (a) reuse `ChannelRouter` with a `TuiChannel` adapter, or (b) drive `agent.run` directly with a `SessionManager` + minimal local loop. **Option (b) is simpler and avoids the async polling machinery** — the TUI owns its own asyncio loop, calls `sm.get_or_create_session("tty", "tui")`, loads history, calls `await agent.run(history, session_id, callbacks)`.
- `/commands` already exist as CLI subcommands + Telegram `SLASH_COMMANDS`. The TUI reuses the same handlers (shell out to `aureon_agent.__main__` for `sessions`/`doctor`/`status`/`mcp`/`cron`/`skills`/`logs`/`version`, and handle `new`/`help` locally).
- `confirm_with_captain` uses an **inline keyboard** on Telegram — but in a TUI there's no Telegram keyboard. For destructive ops in the TUI, confirmation must fall back to **typed** yes/no (the `router.handle_message` typed-fallback path still works) OR a local `input()` prompt. The TUI loop should resolve `pending_confirmations` from typed input.

## Design

### New: `aureon_agent/tui.py` — interactive session REPL
- `cmd_tui(args)` in `__main__.py` registers `tui` subcommand → `run_tui()`.
- `run_tui()`:
  - Build `SessionManager` (same `data/sessions.db`), `SkillLoader`, `ToolRegistry`, `agent_runtime` (reuse `cli.py`'s boot path — extract a `build_runtime()` helper if needed so TUI + bot share it).
  - **Boot mode:**
    - default → **new session**: `session_id = sm.get_or_create_session("tty", "tui")` (fresh history).
    - `--handoff telegram:723865496` → load that session's history so the terminal continues the Telegram chat. (Validate the session exists via `sm.list_sessions()`; error if not.)
    - `--session <id>` → resume a specific `tui:` session by id.
  - Print a banner (version, session id, "type /help for commands").
  - **REPL loop** (`async`):
    - **Use `prompt_toolkit`** for the input line — gives command history (Up/Down), basic emacs keybindings, and a clean prompt. Add `prompt_toolkit` to `requirements.txt` (pure-python, no native build, already common in Hermes/Claude-style CLIs). Fallback to plain `input()` only if import fails (keeps it runnable in minimal envs).
      ```python
      from prompt_toolkit import PromptSession
      psession = PromptSession(message="aureon> ", enable_history_search=True)
      line = await psession.prompt_async()  # async, non-blocking
      ```
    - Read line. If starts with `/` → route to command handler (see below). Else → `callbacks = {on_token: stream_to_stdout, on_tool_use: print_tool_use}`, `history = await sm.get_history(session_id)`, `resp = await agent.run(history, session_id, callbacks)`, `await sm.add_message(session_id, "user", line)` + `("assistant", resp)`.
    - Stream tokens to stdout as they arrive (`on_token`), like the Telegram edit-stream.
- **Ctrl-C / `/exit`** → save + quit.

### `/commands` inside TUI
Reuse the existing command set. Route:
- `help` → print command list.
- `new` → confirm (typed yes/no, since no Telegram keyboard), then `sm.clear_session(session_id)` + reset to fresh `tui` session.
- `sessions` / `doctor` / `status` / `mcp` / `skills` / `logs` / `version` / `cron` → shell out to `python -m aureon_agent.__main__ <cmd>` (same as Telegram `SLASH_COMMANDS`), print output.
- `handoff <session_id>` → switch the live TUI session to that session's history (load + set `session_id`). Lets you pull a Telegram chat into the terminal mid-conversation.

### Confirmation in TUI
- `confirm_with_captain` is Telegram-keyboard based. In TUI there's no keyboard. Two options:
  - **(A)** TUI loop watches `router.pending_confirmations[session_id]`; when set, print "⚠️ Confirm? [yes/no]" and read stdin, `future.set_result(...)`. Reuses the existing fallback.
  - **(B)** Add a `confirm_via_input()` path to `confirm_with_captain` when `channel == "tui"`.
  - Pick **(A)** — least invasive; the typed-fallback already exists in `router.handle_message`, but the TUI drives `agent.run` directly (not `handle_message`), so the TUI loop must resolve the future itself. Implement a small `await _watch_confirm(router, session_id)` that polls/awaits the future and prompts.

## Constraints
- **Reuse, don't duplicate:** `agent.run`, `SessionManager`, `SkillLoader`, `ToolRegistry`, the CLI command handlers. Extract `build_runtime()` from `cli.py` if `start()` tightly couples bot boot.
- **No new heavy deps** — `prompt_toolkit` is pure-python (no native build), already used by Hermes/Claude-style CLIs; add to `requirements.txt` with `input()` fallback on import failure.
- **Secrets never printed** in TUI (same rule as Telegram code-block).
- **Caveman mode** replies apply (SOUL.md).
- **Handoff must validate** the target session exists; refuse unknown ids.
- **Single session per TUI process** (matches the linear-session arch).

## Tests
- `tests/test_tui.py` (new):
  - `run_tui` with `--handoff telegram:723865496` loads that session's history (mock SM, assert history passed to `agent.run`).
  - `run_tui` default → creates `tui:tty` session.
  - `/help` prints command list; `/new` clears + resets.
  - `--handoff <unknown>` → errors gracefully.
  - TUI confirms destructive op via typed input (mock `input` → "yes").

## Verification
- `python -m pytest tests/ -q` green; `ruff` clean.
- `python -m aureon_agent.__main__ tui` → banner, type a message → agent replies, tokens stream.
- `python -m aureon_agent.__main__ tui --handoff telegram:723865496` → continues the Telegram chat (history loaded).
- `/sessions`, `/status`, `/skills`, `/doctor` work inside TUI.
- `/new` clears + starts fresh.

## Suggested commits
- `feat(tui): interactive terminal agent session (new + --handoff boot modes)`
- `feat(tui): /commands routing + typed-confirm fallback`
- `test: tui session boot, handoff, commands, confirm`
