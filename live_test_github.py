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
    github_token = os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_MCP_TOKEN")
    if not github_token:
        print("No GitHub token found.")
        return

    github_bin = os.path.expanduser("~/.npm-global/lib/node_modules/@modelcontextprotocol/server-github/dist/index.js")
    
    ok = await mcp_manager.add_server(
        server_name="github",
        command="node",
        args=[github_bin],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": github_token}
    )
    
    if ok:
        print(f"Connected to github with {len(mcp_manager.clients['github'].tools)} tools.")
    else:
        print("Failed to connect.")
        return
        
    registry = ToolRegistry(skill_loader=None, mcp_manager=mcp_manager)
    agent.setup_registry(registry)
    
    print("\n--- Sending request ---")
    messages = [{"role": "user", "content": "list my open github PRs for vkkatariya/aureon-agent"}]
    result = await agent.run(messages, "test_session", {})
    print(result)
    print("\n")
    
    # Just to avoid the anyio exception during disconnect in tests
    try:
        await mcp_manager.disconnect_all()
    except Exception:
        pass
    
if __name__ == "__main__":
    asyncio.run(main())
