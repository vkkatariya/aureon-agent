"""Telegram adapter: polling, chat ID allowlist, streaming via editMessageText
throttled to 1 edit/sec, 4096-char reply chunking."""
import asyncio
import logging
import time

from telegram.ext import Application, MessageHandler, filters

from channels.base import Channel

logger = logging.getLogger(__name__)

TELEGRAM_MAX_LEN = 4096
EDIT_THROTTLE_SECONDS = 1.0


class TelegramChannel(Channel):
    def __init__(self, token, router, allowed_chats):
        self.token = token
        self.router = router
        self.allowed_chats = allowed_chats
        self._app = None
        self._edit_locks = {}

    async def start(self):
        self._app = Application.builder().token(self.token).build()
        self._app.add_handler(MessageHandler(filters.TEXT, self._on_message))
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self):
        if not self._app:
            return
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()

    async def send_message(self, chat_id, text):
        return await self._app.bot.send_message(chat_id=chat_id, text=text)

    async def edit_message(self, chat_id, message_id, text):
        text_to_send = text or "…"
        logger.info("edit_message: chat_id=%s message_id=%s text=%r (len=%d)", chat_id, message_id, text_to_send[:200] if text_to_send else "<empty>", len(text_to_send))
        try:
            await self._app.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text_to_send)
        except Exception as e:
            logger.debug("edit_message skipped for %s/%s: %s", chat_id, message_id, e)

    async def send_action(self, chat_id, action):
        await self._app.bot.send_chat_action(chat_id=chat_id, action=action)

    async def _on_message(self, update, _context):
        chat_id = str(update.effective_chat.id)
        if chat_id not in self.allowed_chats:
            return

        text = update.message.text
        if not text:
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
