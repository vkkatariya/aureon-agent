import os
import tempfile
import asyncio

from context_builder import (
    build_system_prompt,
    ContextConfig,
    DEFAULT_BRAIN_FILES,
    _load_brain,
)


def _make_workspace(tmp):
    """Create a temp workspace with all 5 brain files + skills dir."""
    os.makedirs(os.path.join(tmp, "skills"), exist_ok=True)
    brain = {
        "SOUL.md": "# Soul\nYou are Aureon, a focused agent.\n",
        "IDENTITY.md": "# Identity\nName: Aureon.\n",
        "WORKFLOW.md": "# Workflow\nBe concise.\n",
        "MEMORY.md": "# Memory\nRemember the user likes short answers.\n",
        "USER.md": "# User\nTZ: Europe/Berlin.\n",
    }
    for fname, content in brain.items():
        with open(os.path.join(tmp, fname), "w") as f:
            f.write(content)
    return tmp


class FakeSkills:
    def get_active_skills(self):
        return []


class FakeSkillsWithOne:
    def get_active_skills(self):
        return [{"name": "x", "description": "y"}]


class FakeMemory:
    async def get_notes(self):
        return {}


class FakeMemoryWithNote:
    async def get_notes(self):
        return {"pref": {"content": "likes tea"}}


def test_brain_loads_all_five():
    async def _test():
        with tempfile.TemporaryDirectory() as tmp:
            ws = _make_workspace(tmp)
            sections = _load_brain(ws, DEFAULT_BRAIN_FILES)
            assert len(sections) == 5
            joined = "\n".join(sections)
            assert "You are Aureon" in joined
            assert "Europe/Berlin" in joined
            assert "Be concise" in joined

    asyncio.run(_test())


def test_missing_brain_file_graceful():
    async def _test():
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "SOUL.md"), "w") as f:
                f.write("# Soul\nhi\n")
            sections = _load_brain(tmp, DEFAULT_BRAIN_FILES)
            assert len(sections) == 1
            assert "hi" in sections[0]

    asyncio.run(_test())


def test_build_system_prompt_includes_brain():
    async def _test():
        with tempfile.TemporaryDirectory() as tmp:
            ws = _make_workspace(tmp)
            prompt = await build_system_prompt(
                ws, FakeSkills(), FakeMemory(), ctx_config=ContextConfig()
            )
            assert "You are Aureon" in prompt
            assert "Europe/Berlin" in prompt
            assert "Be concise" in prompt
            assert "Current time:" in prompt

    asyncio.run(_test())


def test_build_respects_env_override():
    async def _test():
        with tempfile.TemporaryDirectory() as tmp:
            ws = _make_workspace(tmp)
            cfg = ContextConfig(brain_files=["SOUL.md"])
            prompt = await build_system_prompt(
                ws, FakeSkillsWithOne(), FakeMemoryWithNote(), ctx_config=cfg
            )
            assert "You are Aureon" in prompt
            # USER excluded by override
            assert "Europe/Berlin" not in prompt
            # Skills menu + notes still JIT
            assert "Available Skills" in prompt
            assert "likes tea" in prompt

    asyncio.run(_test())


def test_empty_brain_list_jit_only():
    async def _test():
        with tempfile.TemporaryDirectory() as tmp:
            ws = _make_workspace(tmp)
            cfg = ContextConfig(brain_files=[])
            prompt = await build_system_prompt(
                ws, FakeSkillsWithOne(), FakeMemoryWithNote(), ctx_config=cfg
            )
            assert "You are Aureon" not in prompt
            assert "Available Skills" in prompt
            assert "likes tea" in prompt

    asyncio.run(_test())


def test_priority_trim_protects_brain():
    async def _test():
        with tempfile.TemporaryDirectory() as tmp:
            ws = _make_workspace(tmp)
            huge = "# Soul\n" + ("x" * 20000) + "\n"
            with open(os.path.join(tmp, "SOUL.md"), "w") as f:
                f.write(huge)

            cfg = ContextConfig(brain_files=DEFAULT_BRAIN_FILES, token_budget=100)
            prompt = await build_system_prompt(
                ws, FakeSkillsWithOne(), FakeMemoryWithNote(), ctx_config=cfg
            )
            # Brain retained even when over budget
            assert "x" * 100 in prompt

    asyncio.run(_test())


def test_config_env_override():
    os.environ["AUREON_CONTEXT_BRAIN_FILES"] = "SOUL.md,IDENTITY.md"
    os.environ["AUREON_CONTEXT_TOKEN_BUDGET"] = "8000"
    try:
        cfg = ContextConfig.from_env()
        assert cfg.brain_files == ["SOUL.md", "IDENTITY.md"]
        assert cfg.token_budget == 8000
    finally:
        del os.environ["AUREON_CONTEXT_BRAIN_FILES"]
        del os.environ["AUREON_CONTEXT_TOKEN_BUDGET"]
