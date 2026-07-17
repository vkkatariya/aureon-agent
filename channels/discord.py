"""Discord adapter: DM-only (v1), streaming via message.edit() throttled to
1 edit/sec, 2000-char reply chunking. Server/group support is v2."""
import asyncio
import logging
import time

import discord

from channels.base import Channel

logger = logging.getLogger(__name__)

DISCORD_MAX_LEN = 2000
EDIT_THROTTLE_SECONDS = 1.0


class DiscordChannel(Channel):
    def __init__(self, token, router):
        self.token = token
        self.router = router
        self._edit_locks = {}

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        self._client.event(self._on_message)

    async def start(self):
        await self._client.start(self.token)

    async def stop(self):
        await self._client.close()

    async def send_message(self, chat_id, text):
        channel = await self._client.fetch_channel(int(chat_id))
        return await channel.send(text)

    async def edit_message(self, chat_id, message_id, text):
        try:
            channel = await self._client.fetch_channel(int(chat_id))
            message = await channel.fetch_message(int(message_id))
            await message.edit(content=text or "…")
        except Exception as e:
            logger.debug("edit_message skipped for %s/%s: %s", chat_id, message_id, e)

    async def send_action(self, chat_id, _action):
        channel = await self._client.fetch_channel(int(chat_id))
        async with channel.typing():
            pass

    async def _on_message(self, message):
        if message.author.bot or not isinstance(message.channel, discord.DMChannel):
            return

        text = message.content
        if not text:
            return

        chat_id = str(message.channel.id)
        placeholder = await message.channel.send("…")
        lock = self._edit_locks.setdefault(chat_id, asyncio.Lock())
        state = {"text": "", "last_edit": 0.0}

        async def on_token(token):
            state["text"] += token
            now = time.monotonic()
            if now - state["last_edit"] < EDIT_THROTTLE_SECONDS:
                return
            async with lock:
                state["last_edit"] = now
                await self.edit_message(chat_id, str(placeholder.id), state["text"][:DISCORD_MAX_LEN])

        async def on_tool_use(_name, _args):
            await self.send_action(chat_id, "typing")

        try:
            response = await self.router.handle_message(
                "discord", chat_id, text, {"on_token": on_token, "on_tool_use": on_tool_use},
            )
        except Exception as e:
            await self.edit_message(chat_id, str(placeholder.id), f"Error: {e}")
            return

        if not response:
            await self.edit_message(chat_id, str(placeholder.id), "(no response)")
            return

        chunks = [response[i:i + DISCORD_MAX_LEN] for i in range(0, len(response), DISCORD_MAX_LEN)]
        await self.edit_message(chat_id, str(placeholder.id), chunks[0])
        for chunk in chunks[1:]:
            await self.send_message(chat_id, chunk)
