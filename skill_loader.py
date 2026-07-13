"""Loads OpenClaw SKILL.md skills from workspace/skills/.

Two skill shapes are supported:
  - Code skills (handler.py present): tools + async execute(), same contract
    as Tiny-OpenClaw's skill format.
  - Prose skills (the 8 shipped OpenClaw skills — caveman, homelab-*, etc.):
    no handler.py, just a SKILL.md body meant for an LLM to read and follow.
    These get one synthesized tool, `read_skill_<name>`, that returns the
    skill body so the agent can pull it into context on demand.
"""
import importlib.util
import logging
import os

import yaml
from watchfiles import awatch

logger = logging.getLogger(__name__)


def _sanitize(name):
    return name.replace("-", "_").replace(" ", "_")


class SkillLoader:
    def __init__(self, skills_dir):
        self.skills_dir = skills_dir
        self.skills = {}

    async def load(self):
        skills = {}
        if not os.path.isdir(self.skills_dir):
            logger.warning("skills directory not found: %s", self.skills_dir)
            self.skills = skills
            return

        for entry in sorted(os.listdir(self.skills_dir)):
            skill_dir = os.path.join(self.skills_dir, entry)
            skill_md = os.path.join(skill_dir, "SKILL.md")
            if not os.path.isdir(skill_dir) or not os.path.exists(skill_md):
                continue

            try:
                skill = self._load_skill(entry, skill_dir, skill_md)
                skills[skill["name"]] = skill
                logger.info("skill loaded: %s", skill["name"])
            except Exception as e:
                logger.error("failed to load skill %r: %s", entry, e)

        self.skills = skills

    def _load_skill(self, entry, skill_dir, skill_md):
        with open(skill_md) as f:
            frontmatter, body = self._split_frontmatter(f.read())

        name = frontmatter.get("name", entry)
        description = frontmatter.get("description", "").strip()

        handler_py = os.path.join(skill_dir, "handler.py")
        if os.path.exists(handler_py):
            spec = importlib.util.spec_from_file_location(f"skill_{entry}", handler_py)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            tools = getattr(module, "tools", [])
            execute = getattr(module, "execute", None)
        else:
            tool_name = f"read_skill_{_sanitize(name)}"
            tools = [{
                "name": tool_name,
                "description": f"Read full instructions for the '{name}' skill: {description}",
                "parameters": {"type": "object", "properties": {}},
            }]

            async def execute(_tool_name, _tool_input, _context, _body=body):
                return {"skill": name, "content": _body}

        return {
            "name": name,
            "description": description,
            "always": bool(frontmatter.get("always", False)),
            "user_invocable": bool(frontmatter.get("user-invocable", True)),
            "metadata": frontmatter.get("metadata"),
            "body": body,
            "tools": tools,
            "execute": execute,
        }

    @staticmethod
    def _split_frontmatter(content):
        if not content.startswith("---"):
            return {}, content
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content
        _, raw_frontmatter, body = parts
        frontmatter = yaml.safe_load(raw_frontmatter) or {}
        return frontmatter, body.strip()

    def get_active_skills(self):
        return [{"name": s["name"], "description": s["description"]} for s in self.skills.values()]

    def get_tools(self):
        tools = []
        for skill in self.skills.values():
            tools.extend(skill["tools"])
        return tools

    async def execute_tool(self, tool_name, tool_input, context):
        for skill in self.skills.values():
            if any(t["name"] == tool_name for t in skill["tools"]):
                if skill["execute"]:
                    return await skill["execute"](tool_name, tool_input, context)
        return {"error": f"Unknown tool: {tool_name}"}

    async def watch(self):
        """Reload every skill whenever anything under skills_dir changes."""
        async for _ in awatch(self.skills_dir):
            logger.info("skills directory changed, reloading")
            await self.load()
