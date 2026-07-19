# Kickoff: inline-keyboard confirmation (fix OpenClaw-style "type yes" loop)

**Bug:** `confirm_with_captain()` (`aureon_agent/tools/confirm.py`) asks for confirmation by sending a text prompt and waiting for the Captain to **type** "yes"/"confirm"/"approve" (line 43). The reply is resolved via `router.pending_confirmations[session_id]` future in `router.handle_message:44`, which consumes the *next typed message* as the answer.

This is the same UX trap OpenClaw hit: the runtime waits on a chat-typed "yes" while the user expects a button — and loops. For a headless box (athena, no GUI), there is no OS "Allow" popup; the right model is an **inline keyboard** (Yes/No buttons) in the chat, exactly like `/new` already does.

**Goal:** Make destructive/expensive confirmation use a Telegram **inline keyboard** (✅ Yes / ❌ No) instead of waiting for typed text. Keep typed "yes" as a fallback so non-Telegram / old-client paths still work.

**Current state (verified):**
- `confirm_with_captain(context, prompt_text, timeout=60)` → sends text via `router.send_message(session_id, ...)`, registers `router.pending_confirmations[session_id] = future`, awaits `future`, checks `reply.strip().lower() in ["yes","y","confirm","proceed","approve"]`. Default deny on timeout.
- `router.send_message(session_id, text)` → splits `channel:client`, calls `channels[channel].send_message(client_id, text)`. Telegram adapter `send_message(chat_id, text, parse_mode=None)` already forwards `parse_mode` to `bot.send_message` — extend with `reply_markup`.
- `telegram.py` already has `CallbackQueryHandler(self._on_callback)` (added for `/new`) + `InlineKeyboardButton`/`InlineKeyboardMarkup` imports + `_on_callback` that handles `NEW_CONFIRM`/`NEW_CANCEL` sentinels and calls `query.answer()`.
- `router.pending_confirmations` exists; `handle_message` resolves it on the next typed message.

## Deliverable

### 1. Telegram adapter: accept `reply_markup` in `send_message`
- `channels/telegram.py:send_message(chat_id, text, parse_mode=None, reply_markup=None)` → pass `reply_markup` through to `bot.send_message`. (No-op for other channels; base class signature updated.)

### 2. Router: `send_confirmation(session_id, text, confirm_data, cancel_data)`
- New method on `ChannelRouter`: builds the inline keyboard (✅ Yes → `confirm_data`, ❌ No → `cancel_data`) and calls `self.send_message(session_id, text, reply_markup=keyboard)`.
- Reuses existing `send_message` routing (`channel:client` split).

### 3. `confirm_with_captain` → send keyboard, not bare text
- Replace the plain `router.send_message(session_id, full_prompt)` with `router.send_confirmation(session_id, full_prompt, CONFIRM_YES, CONFIRM_NO)`.
- Static sentinels `CONFIRM_YES = "confirm_yes"` / `CONFIRM_NO = "confirm_no"` (≤64 bytes, no secrets) — defined in `telegram.py` alongside `NEW_CONFIRM`/`NEW_CANCEL`.
- Future still registered in `router.pending_confirmations[session_id]`; the callback (step 4) resolves it with `"yes"`/`"no"`. The existing typed-reply fallback (in `router.handle_message`) still resolves it if Captain types yes — both paths set the future, so no conflict (first wins; `future.done()` guard in `handle_message:46` prevents double-set).

### 4. `telegram.py:_on_callback` → handle confirm sentinels
- Extend `_on_callback`:
  - `if data == CONFIRM_NO:` → `query.edit_message_text("❌ Cancelled.")`; resolve `router.pending_confirmations[session_id].set_result("no")` if present.
  - `if data == CONFIRM_YES:` → `query.edit_message_text("✅ Confirmed.")`; resolve future with `"yes"`.
  - Keep existing `NEW_CONFIRM`/`NEW_CANCEL` handling.
  - Unknown data → warn + ignore (already there).
  - `query.answer()` already called at top (stops spinner).
- Allowlist-checked (already at top of `_on_callback`).
- The future resolution must be guarded (`if not future.done()`) to avoid `InvalidStateError`.

### 5. Cleanup
- `confirm_with_captain` finally-block already deletes the pending future — keep.
- Remove the now-misleading comment block in `confirm.py` (lines 19-23, "mock the logic since clarify tool is Tier 2") — it's stale; the helper is real now.

## Constraints
- **No secrets** in callback data (static sentinels only).
- **Allowlist-checked** callbacks (already enforced in `_on_callback`).
- **Default deny** on timeout (unchanged behavior).
- **Reuse** `/new`'s inline-keyboard machinery — don't duplicate the keyboard-building logic; consider a small helper `_build_confirm_keyboard(confirm_text, cancel_text, confirm_data, cancel_data)` in `telegram.py` shared by `/new` + confirm.
- **Caveman mode** applies to bot text.
- Keep typed-"yes" fallback so non-Telegram channels (Discord) still confirm (Discord `send_message` ignores `reply_markup` gracefully).

## Tests
- `tests/test_telegram_slash.py` (extend): `_on_callback` with `CONFIRM_YES` → `pending_confirmations[session_id]` future resolved `"yes"` + message edited; `CONFIRM_NO` → `"no"`; unknown data → ignored + warned; foreign chat → ignored.
- `tests/test_confirm.py` (new): `confirm_with_captain` sends a keyboard (mock `router.send_confirmation` capture `reply_markup`), resolves `"yes"` on confirm sentinel, `"no"` on cancel, denies on timeout.

## Verification
- `python -m pytest tests/ -q` green; ruff clean.
- Restart bot; trigger a destructive tool (e.g. a `terminal` rm via the agent, or unit-test the flow) → Captain gets an inline Yes/No keyboard, not a "type yes" prompt. Tap Yes → proceeds; tap No → denied. (No more type-yes loop.)
- Typed "yes" still works as fallback.

## Suggested commits
- `feat(telegram): send_message accepts reply_markup; router.send_confirmation helper`
- `fix(confirm): use inline-keyboard confirmation instead of typed yes (resolves OpenClaw-style loop)`
- `test: confirm inline-keyboard + callback sentinel tests`
