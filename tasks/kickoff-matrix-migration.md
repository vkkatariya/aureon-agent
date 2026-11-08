# Kickoff: Matrix Channel as Default (Hermes Parity)

**Branch:** `feat/matrix-channel` (off `dev`)  
**Context:** Captain made Matrix the default messaging platform for Hermes Agent on athena and wants Aureon Agent to follow the same architecture. Aureon Agent currently runs Telegram and Discord. This kickoff migrates Aureon Agent to use self-hosted Matrix (Conduit) as its first-class default communication channel, with strict user allowlisting, E2EE encryption, dual command prefixes (`!` and `/`), cron delivery, and health diagnostics.

---

## 1. Reference Architecture & Lessons Learned (Hermes on athena)

* **Homeserver:** Conduit 0.10.x running in Docker sidecar on athena.
* **Endpoint:** `https://matrix.auxois-wyrm.ts.net` (Tailscale MagicDNS, valid TLS, zero raw TS IPs).
* **Owner:** `@syntaxgrid:auxois-wyrm.ts.net` (mandatory allowlist, all foreign/unauthorized messages dropped silently).
* **Bot Account:** Dedicated account `@aureon-agent:auxois-wyrm.ts.net` (separate from `@hermes-agent:auxois-wyrm.ts.net`).
* **Library:** `mautrix[encryption]>=0.21.0` (pure Python async client + prebuilt ARM64 manylinux wheels for `python-olm` and `pycryptodome` on Python 3.12).
* **E2EE / Encryption:** Element clients enforce Megolm encryption on DMs by default. The adapter must initialize `OlmMachine` with an SQLite crypto store (`data/matrix_crypto.db`).
* **Conduit 0.10 UIA Gotcha:** Cross-signing bootstrap may return 401 on Conduit (mautrix UIA gap); this is non-fatal — per-room and DM Megolm E2EE works fully even if the bot shows an unverified device badge.
* **Command Prefix:** Matrix clients (Element) intercept leading `/` as client-side UI commands. The Matrix adapter must support `!` as primary prefix (`!status`, `!doctor`, `!sessions`, `!help`, `!new`), while keeping `/` as backward-compatible alias.
* **Formatted Output:** Matrix renders `org.matrix.custom.html`. Code blocks must be wrapped in `<pre><code>...</code></pre>`.

---

## 2. Current Codebase State (Verified)

* `channels/base.py`: Defines `Channel(ABC)` with `start()`, `send_message(chat_id, text)`, `edit_message(chat_id, message_id, text)`, `send_action(chat_id, action)`, `stop()`.
* `channels/router.py`: `ChannelRouter` manages multi-channel dispatch, sessions (`channel:client_id`), and confirmations. *Issue:* `send_confirmation()` directly imports `telegram.InlineKeyboardMarkup`, breaking non-Telegram channels.
* `channels/telegram.py`: Reference implementation for streaming edit throttling (1 edit/sec), chunking (4096 chars), allowlisting, and slash-command execution.
* `aureon_agent/config.py`: `AureonConfig` only parses `TELEGRAM_*` and `DISCORD_*` channel variables; validation fails if neither is present.
* `aureon_agent/cli.py`: `build_runtime()` registers Telegram and Discord channels.
* `aureon_agent/cron.py` & `aureon_agent/cron_cli.py`: Delivery targets hardcoded to `telegram`, `discord`, `local`, `all`.
* `aureon_agent/doctor.py`: Health check `check_telegram()` pings Telegram API `getMe`.
* `aureon_agent/status.py`: Formats system status; does not report Matrix channel state.
* `aureon_agent/repl.py`: TUI `--handoff` accepts `telegram:<id>` sessions.

---

## 3. Sub-Tasks & Implementation Spec

### Sub-Task 1: Dependencies & Packaging
* Add `mautrix[encryption]>=0.21.0` to `requirements.txt` and `pyproject.toml`.
* Add `data/matrix_crypto.db*` to `.gitignore`.
* Verify `pip install` resolves cleanly in ARM64 `.venv`.

### Sub-Task 2: Configuration (`aureon_agent/config.py`)
Add Matrix configuration fields to `AureonConfig`:
* `MATRIX_HOMESERVER: str = "https://matrix.auxois-wyrm.ts.net"`
* `MATRIX_USER_ID: Optional[str] = None` (e.g. `@aureon-agent:auxois-wyrm.ts.net`)
* `MATRIX_ACCESS_TOKEN: Optional[str] = None`
* `MATRIX_DEVICE_ID: str = "AUREON_ARM64"`
* `MATRIX_ALLOWED_USERS: str = ""` (CSV, e.g. `@syntaxgrid:auxois-wyrm.ts.net`)
* `MATRIX_HOME_ROOM: Optional[str] = None` (for default alerts and cron delivery)
* `MATRIX_ENCRYPTION: bool = True`
* Update `from_env()`, `from_file()`, `redacted_dict()` (mask `MATRIX_ACCESS_TOKEN`).
* Update `validate()`:
  - If `MATRIX_USER_ID` or `MATRIX_ACCESS_TOKEN` is set, ensure `MATRIX_ALLOWED_USERS` is non-empty.
  - Channel requirement passes if at least ONE of Matrix, Telegram, or Discord is configured.

### Sub-Task 3: Router Decoupling (`channels/router.py`)
* Decouple `send_confirmation()` from `telegram.InlineKeyboardMarkup`:
  - Check if target channel has native `send_confirmation` method (Telegram).
  - For channels without inline buttons (Matrix, Discord), send standard prompt text instructing user to reply "yes"/"no" or react with emojis.
  - Keep `router.pending_confirmations` resolution compatible with typed "yes"/"no" replies and callback events.

### Sub-Task 4: Matrix Channel Adapter (`channels/matrix.py`)
Implement `MatrixChannel(Channel)`:
1. **Initialization:**
   * Accept homeserver, user_id, access_token, device_id, allowed_users, home_room, encryption, router, data_dir.
   * Parse `allowed_users` into a normalized `set[str]`.
2. **Lifecycle (`start`, `stop`):**
   * Instantiate `mautrix.client.Client(base_url=homeserver, mxid=user_id, token=access_token)`.
   * If `encryption=True`:
     - Setup SQLite crypto store at `data/matrix_crypto.db`.
     - Initialize `OlmMachine(client, crypto_store, state_store)`.
     - Load machine keys and start encryption listener.
   * Register event handlers for:
     - `m.room.member` (invites): auto-join if `sender in self.allowed_users`; ignore/reject otherwise.
     - `m.room.message`: handle incoming messages.
   * Start `client.sync_forever()`.
   * `stop()`: cancel sync task, close OlmMachine, close aiohttp client session.
3. **Inbound Message Processing (`_on_message`):**
   * Ignore events where `event.sender == self.user_id`.
   * Security gate: check `event.sender in self.allowed_users`. Drop unauthorized messages silently.
   * Event deduplication: keep fixed-size cache (1000 IDs) of processed `event_id`s.
   * Extract plaintext content.
   * Intercept commands starting with `!` or `/`:
     - Map `status`, `doctor`, `sessions`, `version`, `mcp`, `cron`, `logs`, `skills`, `new` to CLI subcommands.
     - Wrap command output in `<pre><code>...</code></pre>` HTML.
     - Special-case `!new` / `/new`: clear session history.
     - Special-case `!lesson` / `/lesson`: record lesson.
   * Non-command message:
     - Route to `self.router.handle_message("matrix", room_id, text, callbacks)`.
     - Track `on_token` callback -> stream deltas via `edit_message` (throttled to 1.0s).
     - Track `on_tool_use` -> send typing indicator via `set_typing(room_id, True)`.
4. **Outbound Messaging (`send_message`, `edit_message`, `send_action`):**
   * `send_message(chat_id, text)`:
     - Convert Markdown / plain text to Matrix HTML format (`format="org.matrix.custom.html"`, `formatted_body=html_text`).
     - If message exceeds 15,000 chars, split into chunks.
     - Send via `client.send_message_event(room_id, EventType.ROOM_MESSAGE, content)`.
     - Return sent `event_id`.
   * `edit_message(chat_id, message_id, text)`:
     - Send `m.room.message` with `m.relates_to = {"rel_type": "m.replace", "event_id": message_id}` and `m.new_content`.
   * `send_action(chat_id, action)`:
     - If `action == "typing"`: call `client.set_typing(room_id, typing=True, timeout=10000)`.

### Sub-Task 5: CLI Runtime & Startup (`aureon_agent/cli.py`)
* In `build_runtime()`:
  - Check for `config.MATRIX_HOMESERVER` and `config.MATRIX_ACCESS_TOKEN`.
  - Instantiate and register `MatrixChannel` with `router.register("matrix", matrix_channel)`.
  - Prioritize Matrix as default communication channel when configured.

### Sub-Task 6: Cron Delivery (`aureon_agent/cron.py` & `cron_cli.py`)
* `aureon_agent/cron_cli.py`:
  - Update `--deliver` argument choices: `["matrix", "telegram", "discord", "local", "all"]`.
  - Default `--deliver` to `"matrix"` if Matrix is configured in `.env`.
* `aureon_agent/cron.py`:
  - In `_deliver()`:
    - Add case `elif deliver == "matrix":`.
    - Deliver to `job.get("chat_id")` or fallback to `config.MATRIX_HOME_ROOM`.
    - Format key as `matrix:<room_id>` and call `self.router.send_message(session_key, text)`.
    - Ensure `deliver == "all"` fans out to Matrix.

### Sub-Task 7: Health Checks & Status (`doctor.py`, `status.py`)
* `aureon_agent/doctor.py`:
  - Add `check_matrix() -> Tuple[str, str]`:
    - Probe `/_matrix/client/versions` via `httpx` (connectivity check).
    - Probe `/_matrix/client/v3/account/whoami` with Bearer token (auth check).
    - Check `MATRIX_ALLOWED_USERS` contains valid MXIDs.
    - Check `data/matrix_crypto.db` presence if encryption enabled.
  - Add `("Matrix API", check_matrix)` to `doctor()` checklist.
* `aureon_agent/status.py`:
  - In `gather_status()`: query Matrix status (homeserver, bot MXID, allowed users, crypto status).
  - In `render_status()`: display Matrix in the Channel & Runtime section.

### Sub-Task 8: Setup Wizard & TUI Handoff (`setup.py`, `repl.py`)
* `aureon_agent/repl.py`:
  - Support continuing Matrix sessions: `/handoff matrix:<room_id>`.
* `aureon_agent/setup.py`:
  - Add interactive Matrix Channel setup section: prompt for Homeserver, User ID, Access Token, Allowed Users.

---

## 4. Verification & Testing Strategy

1. **Unit Tests:**
   * `tests/test_config.py`: Matrix env parsing, validation (allowed users check), token redaction.
   * `tests/test_router.py`: Decoupled confirmation flow (plain text fallback vs Telegram).
   * `tests/test_matrix_channel.py`:
     - Allowlist gate: foreign senders dropped silently.
     - Auto-join: accept invite from allowed sender, reject unauthorized sender.
     - Dual prefix command parsing: `!status` and `/status` route identically.
     - Edit throttling: multiple rapid tokens buffered to 1 edit/sec.
     - Outbound chunking: >15K byte messages cleanly chunked.
   * `tests/test_cron.py`: Cron delivery to `matrix:<room_id>`.
   * `tests/test_doctor.py`: Mock Matrix API responses (200 OK, 401 Unauthorized, connection error).
2. **Quality Gates:**
   * All unit tests pass: `pytest tests/` (160+ tests).
   * Linter clean: `ruff check .` with zero errors or warnings.
   * No hardcoded tokens or secrets in git.
3. **Live Verification (Athena):**
   * Configure `.env` with `@aureon-agent` credentials.
   * Run `aureon-agent doctor`: verify Matrix API check is green.
   * Start service / interactive TUI.
   * Send test DM from `@syntaxgrid:auxois-wyrm.ts.net` in Element: verify response streaming.
   * Run `!status` and `!help` in Element: verify code block formatting.

---

## 5. Execution Contract & Worker Rules

* **Branch:** `feat/matrix-channel` off `dev`.
* **Commits:** `feat(channel): ...`, `test(channel): ...`, `chore: ...`.
* **Verification before claim:** tests pass, diff clean, logs verified.
* **Last step:** Write entry in `tasks/DEVLOG.md`, update `tasks/todo.md`, push branch to GitHub. Do not merge to `dev` without Captain review.
