"""Standalone smoke checks (no pytest — run directly: python tests/smoke.py).

Covers: skill loading, Memory roundtrip, SessionManager roundtrip, context
builder token budget, and a reachability check against Ollama (skipped, not
failed, if Ollama isn't running).
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from context_builder import build_system_prompt
from memory import Memory
from session_manager import SessionManager
from skill_loader import SkillLoader

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_DIR = os.path.join(BASE_DIR, "workspace")

EXPECTED_SKILLS = {
    "caveman", "homelab-deploy", "homelab-health", "homelab-scaffold",
    "nano-banana-pro", "notion", "openclaw-health", "project-init",
}

TOKEN_BUDGET_CHARS = 8000 * 5  # matches context_builder.TOKEN_BUDGET (8000 chars) + margin


async def check_skills():
    loader = SkillLoader(os.path.join(WORKSPACE_DIR, "skills"))
    await loader.load()
    loaded = set(loader.skills.keys())
    missing = EXPECTED_SKILLS - loaded
    assert not missing, f"skills failed to load: {missing}"
    assert loader.get_tools(), "no tools registered from any skill"
    print(f"PASS skills: {len(loaded)} loaded ({', '.join(sorted(loaded))})")
    return loader


async def check_memory():
    with tempfile.TemporaryDirectory() as tmp:
        memory = Memory(os.path.join(tmp, "memory.db"))
        await memory.connect()
        await memory.set("note:likes", "coffee")
        await memory.set("scratch:x", 42)
        assert await memory.get("note:likes") == "coffee"
        assert await memory.get("scratch:x") == 42
        notes = await memory.get_notes()
        assert notes == {"likes": "coffee"}
        await memory.close()
    print("PASS memory: set/get + note:* roundtrip")


async def check_sessions():
    with tempfile.TemporaryDirectory() as tmp:
        sessions = SessionManager(os.path.join(tmp, "sessions.db"))
        await sessions.connect()
        session_id = await sessions.get_or_create_session("123", "telegram")
        assert session_id == "telegram:123"
        await sessions.add_message(session_id, "user", "hello")
        await sessions.add_message(session_id, "assistant", "hi there")
        history = await sessions.get_history(session_id)
        assert [m["role"] for m in history] == ["user", "assistant"]
        assert history[0]["content"] == "hello"
        await sessions.close()
    print("PASS sessions: create/add_message/get_history roundtrip")


async def check_context_builder(loader):
    with tempfile.TemporaryDirectory() as tmp:
        memory = Memory(os.path.join(tmp, "memory.db"))
        await memory.connect()
        await memory.set("note:likes", "coffee")
        prompt = await build_system_prompt(WORKSPACE_DIR, loader, memory)
        await memory.close()
    assert prompt, "system prompt is empty"
    approx_tokens = len(prompt) // 4
    assert len(prompt) < TOKEN_BUDGET_CHARS, f"system prompt too large: ~{approx_tokens} tokens"
    print(f"PASS context_builder: ~{approx_tokens} tokens ({len(prompt)} chars)")


async def check_ollama_reachable():
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            res = await client.get(f"{base_url}/models")
        if res.status_code == 200:
            print(f"PASS ollama: reachable at {base_url}")
        else:
            print(f"SKIP ollama: {base_url} returned {res.status_code}")
    except (httpx.ConnectError, httpx.TimeoutException):
        print(f"SKIP ollama: {base_url} not reachable (expected if Ollama isn't running)")


async def main():
    loader = await check_skills()
    await check_memory()
    await check_sessions()
    await check_context_builder(loader)
    await check_ollama_reachable()
    print("\nsmoke tests: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
