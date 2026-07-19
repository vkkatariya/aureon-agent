"""Telegram adapter: polling, chat ID allowlist, streaming via editMessageText
throttled to 1 edit/sec, 4096-char reply chunking, and /slash command surface."""
import asyncio
import logging
import subprocess
import sys
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from channels.base import Channel

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LEN = 4096
CODEBLOCK_CHUNK_LEN = 3900  # leave headroom for the ``` fences + escapes
EDIT_THROTTLE_SECONDS = 1.0


def _md_code_block(text: str) -> str:
    """Wrap text in a MarkdownV2 fenced code block. Inside a code block only
    backslash and backtick need escaping (Telegram MarkdownV2 rules)."""
    escaped = text.replace("\\", "\\\\").replace("`", "\\`")
    return f"```\n{escaped}\n```"


def _chunk_for_codeblock(text: str) -> list:
    text = text.strip()
    return [text[i:i + CODEBLOCK_CHUNK_LEN]
            for i in range(0, len(text), CODEBLOCK_CHUNK_LEN)] or [""]

# Slash commands -> aureon-agent CLI subcommand (reuse 1:1, no logic duplication).
# Nested subcommands (mcp/cron) handled specially below.
SLASH_COMMANDS = {
    "sessions": ["sessions"],
    "doctor": ["doctor"],
    "status": ["status"],
    "version": ["version"],
    "mcp": ["mcp", "list"],
    "cron": ["cron", "list"],
    "logs": ["logs"],
    "skills": ["skills", "list"],
}

# /new confirmation inline-keyboard callback payloads (<= 64 bytes, no secrets).
NEW_CONFIRM = "new_confirm"
NEW_CANCEL = "new_cancel"

# confirm_with_captain() inline-keyboard callback payloads (<= 64 bytes, no secrets).
CONFIRM_YES = "confirm_yes"
CONFIRM_NO = "confirm_no"


def _build_confirm_keyboard(confirm_text, cancel_text, confirm_data, cancel_data):
    """Inline Yes/No keyboard shared by /new and confirm_with_captain."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(confirm_text, callback_data=confirm_data),
        InlineKeyboardButton(cancel_text, callback_data=cancel_data),
    ]])


class TelegramChannel(Channel):
    def __init__(self, token, router, allowed_chats):
        self.token = token
        self.router = router
        self.allowed_chats = allowed_chats
        self._app = None
        self._edit_locks = {}

    async def start(self):
        self._app = Application.builder().token(self.token).build()
        # Commands are routed inside _on_message (which reliably fires for
        # sendMessage-injected /commands); PTB's CommandHandler entity
        # matching was unreliable for API-sent commands.
        self._app.add_handler(MessageHandler(filters.TEXT, self._on_message))
        self._app.add_handler(CallbackQueryHandler(self._on_callback))
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self):
        if not self._app:
            return
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()

    async def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        return await self._app.bot.send_message(
            chat_id=chat_id, text=text, parse_mode=parse_mode, reply_markup=reply_markup,
        )

    async def edit_message(self, chat_id, message_id, text):
        text_to_send = text or "…"
        logger.info("edit_message: chat_id=%s message_id=%s text=%r (len=%d)", chat_id, message_id, text_to_send[:200] if text_to_send else "<empty>", len(text_to_send))
        try:
            await self._app.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text_to_send)
        except Exception as e:
            logger.debug("edit_message skipped for %s/%s: %s", chat_id, message_id, e)

    async def send_action(self, chat_id, action):
        await self._app.bot.send_chat_action(chat_id=chat_id, action=action)

    async def _on_command(self, update, _context):
        chat_id = str(update.effective_chat.id)
        if chat_id not in self.allowed_chats:
            return

        # Parse: "/cmd@botname args" -> "cmd"
        raw = (update.message.text or "").lstrip("/").split()
        if not raw:
            return
        cmd = raw[0].split("@")[0].lower()
        logger.info("telegram._on_command: chat_id=%s cmd=%s", chat_id, cmd)

        if cmd == "help":
            lines = ["**Available commands:**"] + [
                f"/{name} — {desc}" for name, desc in [
                    ("new", "start a new session (clears history)"),
                    ("skills", "list loaded doctrine skills"),
                    ("sessions", "list all chat sessions"),
                    ("doctor", "health checks"),
                    ("status", "systemd service status"),
                    ("mcp", "list MCP servers + tools"),
                    ("cron", "list cron jobs"),
                    ("logs", "recent bot logs"),
                    ("version", "agent version"),
                    ("help", "this message"),
                ]
            ]
            await self.send_message(chat_id, "\n".join(lines))
            return

        if cmd == "new":
            keyboard = _build_confirm_keyboard(
                "✅ Yes, start new", "❌ No, keep", NEW_CONFIRM, NEW_CANCEL,
            )
            await self._app.bot.send_message(
                chat_id=chat_id,
                text=(f"Start a new session? This clears the current chat history "
                      f"(telegram:{chat_id}). Cannot be undone."),
                reply_markup=keyboard,
            )
            return

        cli_args = SLASH_COMMANDS.get(cmd)
        if not cli_args:
            await self.send_message(chat_id, f"Unknown command: /{cmd}")
            return

        await self.send_action(chat_id, "typing")
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "aureon_agent.__main__", *cli_args],
                capture_output=True, text=True, timeout=60,
            )
            out = (proc.stdout or proc.stderr or "").strip()
        except Exception as e:
            out = f"Error running /{cmd}: {e}"

        if not out:
            out = f"(/ {cmd} produced no output)"
        # Wrap CLI output (Rich tables) in a MarkdownV2 code block so Telegram
        # renders it as aligned monospace — box-drawing chars and column
        # alignment collapse in plain text. Chunk first (leaving room for the
        # fences), then fence each chunk independently.
        for chunk in _chunk_for_codeblock(out):
            await self.send_message(chat_id, _md_code_block(chunk), parse_mode="MarkdownV2")

    async def _on_callback(self, update, _context):
        query = update.callback_query
        chat_id = str(update.effective_chat.id)
        if chat_id not in self.allowed_chats:
            return
        await query.answer()  # stop the button's loading spinner

        data = query.data
        if data == NEW_CANCEL:
            await query.edit_message_text("Kept current history.")
            return
        if data == CONFIRM_NO:
            await query.edit_message_text("❌ Cancelled.")
            self._resolve_confirm(chat_id, "no")
            return
        if data == CONFIRM_YES:
            await query.edit_message_text("✅ Confirmed.")
            self._resolve_confirm(chat_id, "yes")
            return
        if data != NEW_CONFIRM:
            logger.warning("telegram._on_callback: unknown callback data %r", data)
            return

        session_id = f"telegram:{chat_id}"
        cleared = await self.router.sessions.clear_session(session_id)
        if cleared:
            await query.edit_message_text(f"✅ New session started. Cleared {cleared} message(s).")
        else:
            await query.edit_message_text("✅ New session — chat already fresh.")

    def _resolve_confirm(self, chat_id, result):
        """Resolve a pending confirm_with_captain future for this chat (if any)."""
        session_id = f"telegram:{chat_id}"
        router = self.router
        pending = getattr(router, "pending_confirmations", None)
        if not pending:
            return
        future = pending.get(session_id)
        if future and not future.done():
            future.set_result(result)

    async def _on_message(self, update, _context):
        chat_id = str(update.effective_chat.id)
        if chat_id not in self.allowed_chats:
            return

        text = update.message.text
        if not text:
            return

        # Route slash commands to the command handler (no LLM).
        if text.startswith("/"):
            await self._on_command(update, _context)
            return

        placeholder = await update.message.reply_text("…")
        lock = self._edit_locks.setdefault(chat_id, asyncio.Lock())
        state = {"text": "", "last_edit": 0.0}

        async def on_token(token):
            state["text"] += token
            now = time.monotonic()
            if now - state["last_edit"] < EDIT_THROTTLE_SECONDS:
                return
            async with lock:
                state["last_edit"] = now
                await self.edit_message(chat_id, placeholder.message_id, state["text"][:TELEGRAM_MAX_LEN])

        async def on_tool_use(_name, _args):
            await self.send_action(chat_id, "typing")

        try:
            response = await self.router.handle_message(
                "telegram", chat_id, text, {"on_token": on_token, "on_tool_use": on_tool_use},
            )
        except Exception as e:
            await self.edit_message(chat_id, placeholder.message_id, f"Error: {e}")
            return

        if not response:
            logger.warning("telegram._on_message: response is empty/None, falling back to streamed state text. chat_id=%s, last_user=%r", chat_id, text[:100])
            # Fallback: edit the placeholder with whatever text was streamed during the LLM response
            # (state["text"] may be empty if the LLM returned nothing, but at least try)
            if state.get("text", "").strip():
                await self.edit_message(chat_id, placeholder.message_id, state["text"])
                logger.info("telegram._on_message: used streamed state text fallback, length=%d", len(state["text"]))
            else:
                await self.edit_message(chat_id, placeholder.message_id, "(no response from LLM — try again or simplify your message)")
                logger.error("telegram._on_message: BOTH final response and streamed state are empty. LLM returned nothing. chat_id=%s", chat_id)
            return

        logger.info("telegram._on_message: response received, length=%d, chat_id=%s", len(response), chat_id)
        chunks = [response[i:i + TELEGRAM_MAX_LEN] for i in range(0, len(response), TELEGRAM_MAX_LEN)]
        await self.edit_message(chat_id, placeholder.message_id, chunks[0])
        for chunk in chunks[1:]:
            await self.send_message(chat_id, chunk)
