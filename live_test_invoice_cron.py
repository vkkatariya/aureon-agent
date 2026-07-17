"""Engine C (variant 2) live verification — runs the invoice-weekly cron job's
prompt through a full aureon agent turn (skills + patched gmail MCP registry),
exactly as CronScheduler._run_job would, but out-of-process so it doesn't need
the production bot restarted.

Proves the agent-scheduler path end-to-end: the LLM reads the prompt and chains
mcp_gmail_search_mail -> read_message -> download_attachment to save real
invoices. Hits REAL Gmail (readonly) + the LLM. Not a pytest test.

Run:  python live_test_invoice_cron.py
"""
import asyncio
import os
import sys

from dotenv import load_dotenv

from agent_runtime import AgentRuntime
from aureon_agent.cli import DATA_DIR, WORKSPACE_DIR, _parse_mcp_servers
from aureon_agent.mcp_client import MCPManager
from aureon_agent.tool_registry import ToolRegistry
from skill_loader import SkillLoader

# Wider window than the real 7d job so there's a known invoice to download
# (proves the full chain even in a quiet week).
PROMPT = (
    "Download recent invoices. Steps, using the gmail tools:\n"
    '1. mcp_gmail_search_mail account="vishal" '
    'query="subject:(invoice OR rechnung) has:attachment newer_than:400d" limit=3\n'
    '2. For the FIRST result only, mcp_gmail_read_message id=<id> account="vishal" '
    "to get attachments[] (each has an attachmentId).\n"
    "3. For the first attachment whose filename ends in .pdf, call "
    'mcp_gmail_download_attachment account="vishal" messageId=<id> '
    'attachmentId=<attachmentId> filename=<filename> destDir="~/dev-shared/docs/invoices".\n'
    "4. Reply with the saved filename."
)


async def main():
    load_dotenv(override=True)
    os.makedirs(DATA_DIR, exist_ok=True)

    skills = SkillLoader(os.path.join(WORKSPACE_DIR, "skills"))
    await skills.load()

    agent = AgentRuntime(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
        api_key=os.getenv("OLLAMA_API_KEY"),
        model=os.getenv("OLLAMA_MODEL", "minimax-m2.5:cloud"),
        skill_loader=skills,
        workspace_dir=WORKSPACE_DIR,
        memory=None,
        fallback_base_url=os.getenv("OLLAMA_CLOUD_BASE_URL", "https://ollama.com/v1"),
        fallback_api_key=os.getenv("OLLAMA_API_KEY"),
    )

    mcp = MCPManager()
    for cfg in _parse_mcp_servers():
        if cfg["server_name"] == "gmail":
            await mcp.add_server(**cfg)
    if "gmail" not in mcp.clients:
        print("FAIL: gmail MCP server not configured/connected")
        return

    tools = [t["name"] for t in mcp.get_tools()]
    print("gmail MCP tools:", tools)
    assert "mcp_gmail_download_attachment" in tools

    agent.setup_registry(ToolRegistry(skill_loader=skills, mcp_manager=mcp))

    history = [{"role": "user", "content": PROMPT}]
    try:
        result = await asyncio.wait_for(
            agent.run(history, "cron:invoice-weekly:live", {}), timeout=300)
        print("\n--- agent reply ---\n", result)
    finally:
        try:
            await mcp.disconnect_all()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
