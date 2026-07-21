"""Entry point: loads env, wires Memory + SessionManager + SkillLoader + AgentRuntime
+ ChannelRouter, starts channel adapters, handles graceful shutdown."""
import asyncio
import logging
import os
import signal
import sys

from dotenv import load_dotenv

from agent_runtime import AgentRuntime
from aureon_agent.pidlock import acquire_lock, release_lock
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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
DATA_DIR = os.path.join(BASE_DIR, "data")


def _parse_mcp_servers() -> list[dict]:
    """Parse MCP server configurations from environment variables.

    Convention: each MCP server has an enable flag + its required env vars.
    Returns list of dicts ready for MCPManager.add_server(**cfg).
    """
    servers = []

    # Notion MCP server (stdio)
    # Reads NOTION_API_KEY (hermes-style) or NOTION_TOKEN (fallback).
    # Server binary is `notion-mcp-server` (NOT the unscoped
    # `mcp-server-notion` canary — that's a typosquat/security risk).
    notion_token = os.getenv("NOTION_API_KEY") or os.getenv("NOTION_TOKEN")
    if notion_token:
        # Absolute path — systemd service PATH may not include ~/.npm-global/bin
        notion_bin = os.path.expanduser(
            "~/.npm-global/lib/node_modules/notion-mcp-server/build/index.js"
        )
        if not os.path.exists(notion_bin):
            logger.warning("Notion MCP binary not found at %s", notion_bin)
        else:
            servers.append({
                "server_name": "notion",
                "command": "node",
                "args": [notion_bin],
                "env": {"NOTION_TOKEN": notion_token},
            })

    # GitHub MCP server (stdio) — Phase 7.4
    # Reads GITHUB_TOKEN (hermes-style) or GITHUB_MCP_TOKEN (fallback).
    github_token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_MCP_TOKEN")
    if github_token:
        github_bin = os.path.expanduser(
            "~/.npm-global/lib/node_modules/@modelcontextprotocol/server-github/dist/index.js"
        )
        if not os.path.exists(github_bin):
            logger.warning("GitHub MCP binary not found at %s", github_bin)
        else:
            servers.append({
                "server_name": "github",
                "command": "node",
                "args": [github_bin],
                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": github_token},
            })

    # Gmail MCP server (stdio) — Phase 7.3.2 (OAuth)
    # Uses oliverkoast/multi-email-mcp (gmail.readonly).
    # Token cache lives in tokens/ dir, requires 'npm run auth vishal' first.
    gmail_client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    gmail_client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")

    if gmail_client_id and gmail_client_secret:
        gmail_bin = os.path.expanduser(
            "~/.npm-global/lib/node_modules/multi-email-mcp/src/server.js"
        )
        if not os.path.exists(gmail_bin):
            logger.warning("Gmail MCP binary not found at %s", gmail_bin)
        else:
            token_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tokens", "vishal.json")
            if not os.path.exists(token_path):
                logger.warning("Gmail OAuth token not found at %s (run 'npm run auth vishal')", token_path)
            else:
                servers.append({
                    "server_name": "gmail",
                    "command": "node",
                    "args": [gmail_bin],
                    "env": {
                        "MAIL_ACCOUNTS": "vishal",
                        "MAIL_VISHAL_PROVIDER": "gmail-api",
                        "MAIL_VISHAL_EMAIL": os.environ.get("EMAIL_ADDRESS") or "vishal@example.com",
                        "GOOGLE_OAUTH_CLIENT_ID": gmail_client_id,
                        "GOOGLE_OAUTH_CLIENT_SECRET": gmail_client_secret,
                    },
                })

    return servers


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


async def build_runtime(*, watch_skills=True, connect_mcp=True):
    """Wire the shared agent runtime (memory, sessions, skills, MCP, registry).

    Reused by the bot (`main`) and the interactive TUI (`repl`) so both drive the
    exact same `agent.run`. Does not touch channels, cron, PID lock, or signals.
    Returns a dict of the built components.

    `connect_mcp=False` skips spawning the MCP stdio servers — the TUI uses this
    for a fast boot + clean exit (the anyio stdio teardown can block); it still
    gets the doctrine skills, just not the MCP-backed tools.
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    memory = Memory(os.path.join(DATA_DIR, "memory.db"))
    await memory.connect()

    sessions = SessionManager(os.path.join(DATA_DIR, "sessions.db"))
    await sessions.connect()

    skills = SkillLoader(os.path.join(WORKSPACE_DIR, "skills"))
    await skills.load()
    reload_task = asyncio.create_task(skills.watch()) if watch_skills else None

    thinking_env = os.getenv("AUREON_THINKING", "false").lower() == "true"
    try:
        thinking_budget = int(os.getenv("AUREON_THINKING_BUDGET", "1024"))
    except ValueError:
        thinking_budget = 1024

    # Only enable the cloud fallback when BOTH a URL and a key are present.
    # An unauthenticated cloud fallback (key empty) yields 401 on every blip
    # of the local endpoint — better to fail loud than fail to a dead fallback.
    _cloud_url = os.getenv("OLLAMA_CLOUD_BASE_URL")
    _cloud_key = os.getenv("OLLAMA_API_KEY")
    _fallback_base = _cloud_url if (_cloud_url and _cloud_key) else None

    agent = AgentRuntime(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
        api_key=os.getenv("OLLAMA_API_KEY"),
        model=os.getenv("OLLAMA_MODEL", "minimax-m2.5:cloud"),
        skill_loader=skills,
        workspace_dir=WORKSPACE_DIR,
        memory=memory,
        fallback_base_url=_fallback_base,
        fallback_api_key=_cloud_key,
        thinking=thinking_env,
        thinking_budget=thinking_budget,
    )

    # ── MCP servers ───────────────────────────────────────────────
    from aureon_agent.mcp_client import MCPManager
    from aureon_agent.tool_registry import ToolRegistry

    mcp_manager = MCPManager()

    # Connect configured MCP servers (fail soft — log warning, continue without)
    if connect_mcp:
        for server_cfg in _parse_mcp_servers():
            ok = await mcp_manager.add_server(**server_cfg)
            if ok:
                logger.info("MCP server '%s' connected (%d tools)",
                            server_cfg["server_name"], len(mcp_manager.clients[server_cfg["server_name"]].tools))

    # ── Tool registry ─────────────────────────────────────────────
    registry = ToolRegistry(skill_loader=skills, mcp_manager=mcp_manager if mcp_manager.clients else None)
    agent.setup_registry(registry)
    logger.info("tool registry: %d tools (%s)",
                registry.tool_count,
                ", ".join(f"{k}: {len(v)}" for k, v in registry.list_tools_by_backend().items() if v))

    return {
        "memory": memory, "sessions": sessions, "skills": skills,
        "agent": agent, "mcp_manager": mcp_manager, "registry": registry,
        "reload_task": reload_task,
    }


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

    rt = await build_runtime()
    memory = rt["memory"]
    sessions = rt["sessions"]
    agent = rt["agent"]
    mcp_manager = rt["mcp_manager"]
    reload_task = rt["reload_task"]

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

    # ── Cron scheduler ────────────────────────────────────────────
    from aureon_agent.cron import CronScheduler
    cron = CronScheduler(
        db_path=os.path.join(DATA_DIR, "cron_jobs.db"),
        agent_runtime=agent,
        channel_router=router,
        workspace_dir=WORKSPACE_DIR,
        default_chat_id=os.getenv("TELEGRAM_ALLOWED_CHATS", "").split(",")[0].strip(),
    )
    await cron.start()
    logger.info("cron scheduler started")

    try:
        await shutdown.wait()
    finally:
        # Always release the PID lock on the way out, regardless of
        # whether shutdown came from SIGINT, SIGTERM, or an exception.
        release_lock()

    logger.info("shutting down")

    await cron.stop()
    await mcp_manager.disconnect_all()
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
