"""Entry point: loads env, wires Memory + SessionManager + SkillLoader + AgentRuntime
+ ChannelRouter, starts channel adapters, handles graceful shutdown."""
import asyncio
import logging
import os
import signal
import sys

from dotenv import load_dotenv

from agent_runtime import AgentRuntime
from aureon_agent.pidlock import acquire_lock, install_signal_handlers, release_lock
from channels.discord import DiscordChannel
from channels.router import ChannelRouter
from channels.telegram import TelegramChannel
from memory import Memory
from session_manager import SessionManager
from skill_loader import SkillLoader

load_dotenv(override=True)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("aureon-agent")

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
DATA_DIR = os.path.join(BASE_DIR, "data")


async def _start_health_server():
    port = os.getenv("HEALTH_PORT")
    if not port:
        return None
    from aiohttp import web

    async def health(_request):
        return web.json_response({"status": "ok"})

    app = web.Application()
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", int(port))
    await site.start()
    logger.info("health endpoint on http://127.0.0.1:%s/health", port)
    return runner


async def main():
    # PID lock — prevent two instances on the same workspace.
    existing = acquire_lock()
    if existing:
        logger.error(
            "another aureon-agent is already running (pid %s). "
            "If that's stale, remove ~/.cache/aureon-agent.pid and retry.",
            existing,
        )
        sys.exit(1)

    logger.info("aureon-agent starting up")
    os.makedirs(DATA_DIR, exist_ok=True)

    memory = Memory(os.path.join(DATA_DIR, "memory.db"))
    await memory.connect()

    sessions = SessionManager(os.path.join(DATA_DIR, "sessions.db"))
    await sessions.connect()

    skills = SkillLoader(os.path.join(WORKSPACE_DIR, "skills"))
    await skills.load()
    reload_task = asyncio.create_task(skills.watch())

    agent = AgentRuntime(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
        api_key=os.getenv("OLLAMA_API_KEY"),
        model=os.getenv("OLLAMA_MODEL", "minimax-m2.5:cloud"),
        skill_loader=skills,
        workspace_dir=WORKSPACE_DIR,
        memory=memory,
        fallback_base_url=os.getenv("OLLAMA_CLOUD_BASE_URL", "https://ollama.com/v1"),
        fallback_api_key=os.getenv("OLLAMA_API_KEY"),
    )

    router = ChannelRouter(agent, sessions, WORKSPACE_DIR)

    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if telegram_token:
        allowed_chats = {c.strip() for c in os.getenv("TELEGRAM_ALLOWED_CHATS", "").split(",") if c.strip()}
        if not allowed_chats:
            logger.warning("TELEGRAM_ALLOWED_CHATS is empty — all Telegram messages will be dropped")
        router.register("telegram", TelegramChannel(telegram_token, router, allowed_chats))
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not set, Telegram channel disabled")

    discord_token = os.getenv("DISCORD_BOT_TOKEN")
    if discord_token:
        router.register("discord", DiscordChannel(discord_token, router))
    else:
        logger.info("DISCORD_BOT_TOKEN not set, Discord channel disabled")

    health_runner = await _start_health_server()

    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)

    channels_task = asyncio.create_task(router.start_all()) if router.channels else None
    logger.info("aureon-agent running (channels: %s)", ", ".join(router.channels) or "none")

    try:
        await shutdown.wait()
    finally:
        # Always release the PID lock on the way out, regardless of
        # whether shutdown came from SIGINT, SIGTERM, or an exception.
        release_lock()

    logger.info("shutting down")

    reload_task.cancel()
    await router.stop_all()
    if channels_task:
        channels_task.cancel()
    if health_runner:
        await health_runner.cleanup()
    await sessions.close()
    await memory.close()


if __name__ == "__main__":
    asyncio.run(main())
