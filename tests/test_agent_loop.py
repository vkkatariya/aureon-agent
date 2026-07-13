"""End-to-end agent loop check (no pytest — run directly: python tests/test_agent_loop.py).

Exercises the full ReAct loop against a live Ollama endpoint. Skipped (not
failed) if Ollama isn't reachable, since CI doesn't run a local model.
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from agent_runtime import AgentRuntime
from memory import Memory
from skill_loader import SkillLoader

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")


async def ollama_reachable(base_url):
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            res = await client.get(f"{base_url}/models")
        return res.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException):
        return False


async def main():
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    if not await ollama_reachable(base_url):
        print(f"SKIP test_agent_loop: Ollama not reachable at {base_url}")
        return

    with tempfile.TemporaryDirectory() as tmp:
        memory = Memory(os.path.join(tmp, "memory.db"))
        await memory.connect()

        skills = SkillLoader(os.path.join(WORKSPACE_DIR, "skills"))
        await skills.load()

        agent = AgentRuntime(
            base_url=base_url,
            api_key=os.getenv("OLLAMA_API_KEY"),
            model=os.getenv("OLLAMA_MODEL", "minimax-m2.5:cloud"),
            skill_loader=skills,
            workspace_dir=WORKSPACE_DIR,
            memory=memory,
        )

        history = [{"role": "user", "content": "Reply with exactly one word: PONG"}]
        tokens = []

        async def on_token(t):
            tokens.append(t)

        response = await agent.run(history, "test:agent-loop", {"on_token": on_token})

        await memory.close()

    assert response, "agent returned an empty response"
    print(f"PASS test_agent_loop: got response ({len(response)} chars, {len(tokens)} stream chunks)")


if __name__ == "__main__":
    asyncio.run(main())
