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
    gmail_client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    gmail_client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    
    oauth_file = os.path.join(os.path.dirname(__file__), "tokens", ".oauth")
    if os.path.exists(oauth_file):
        with open(oauth_file, "r") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    if k == "GOOGLE_OAUTH_CLIENT_ID" and not gmail_client_id: gmail_client_id = v
                    if k == "GOOGLE_OAUTH_CLIENT_SECRET" and not gmail_client_secret: gmail_client_secret = v

    if not gmail_client_id or not gmail_client_secret:
        print("No Gmail OAuth credentials found. Skipping live test.")
        return

    gmail_bin = os.path.expanduser("~/.npm-global/lib/node_modules/multi-email-mcp/src/server.js")
    token_path = os.path.join(os.path.dirname(__file__), "tokens", "vishal.json")
    if not os.path.exists(token_path):
        print("No Gmail OAuth token cached (run 'npm run auth vishal'). Skipping live test.")
        return
    
    ok = await mcp_manager.add_server(
        server_name="gmail",
        command="node",
        args=[gmail_bin],
        env={
            "MAIL_ACCOUNTS": "vishal",
            "MAIL_VISHAL_PROVIDER": "gmail-api",
            "MAIL_VISHAL_EMAIL": os.environ.get("EMAIL_ADDRESS") or "vishal@example.com",
            "GOOGLE_OAUTH_CLIENT_ID": gmail_client_id,
            "GOOGLE_OAUTH_CLIENT_SECRET": gmail_client_secret,
        }
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
