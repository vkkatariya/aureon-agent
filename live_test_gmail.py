import asyncio
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aureon_agent.mcp_client import MCPManager
from aureon_agent.tool_registry import ToolRegistry
from agent_runtime import AgentRuntime
from memory import Memory

async def main():
    load_dotenv(override=True)
    
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")
    
    memory = Memory(":memory:")
    await memory.connect()
    
    agent = AgentRuntime(
        base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
        api_key=os.getenv("OLLAMA_API_KEY"),
        model=os.getenv("OLLAMA_MODEL", "minimax-m2.5:cloud"),
        skill_loader=None,
        workspace_dir=WORKSPACE_DIR,
        memory=memory,
        fallback_base_url=os.getenv("OLLAMA_CLOUD_BASE_URL", "https://ollama.com/v1"),
        fallback_api_key=os.getenv("OLLAMA_API_KEY"),
    )
    
    mcp_manager = MCPManager()
    gmail_email = os.getenv("EMAIL_ADDRESS")
    gmail_password = os.getenv("EMAIL_PASSWORD")
    if not gmail_email or not gmail_password:
        print("No Gmail credentials found. Skipping live test.")
        return

    gmail_bin = os.path.expanduser("~/.npm-global/lib/node_modules/gmail-mcp-imap/build/index.js")
    
    ok = await mcp_manager.add_server(
        server_name="gmail",
        command="node",
        args=[gmail_bin],
        env={"GMAIL_EMAIL": gmail_email, "GMAIL_APP_PASSWORD": gmail_password}
    )
    
    if ok:
        print(f"Connected to gmail with {len(mcp_manager.clients['gmail'].tools)} tools.")
    else:
        print("Failed to connect.")
        return
        
    registry = ToolRegistry(skill_loader=None, mcp_manager=mcp_manager)
    agent.setup_registry(registry)
    
    print("\n--- Sending request ---")
    messages = [{"role": "user", "content": "list my recent emails"}]
    result = await agent.run(messages, "test_session", {})
    print(result)
    print("\n")
    
    try:
        await mcp_manager.disconnect_all()
    except Exception:
        pass
    
if __name__ == "__main__":
    asyncio.run(main())
