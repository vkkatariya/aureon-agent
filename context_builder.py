"""Assembles the system prompt from doctrine files, active skills, and memory notes."""
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Rough token budget (chars/4 ≈ tokens). Trimmed if exceeded.
TOKEN_BUDGET = 2000
MAX_NOTES = 20


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


async def build_system_prompt(workspace_dir, skill_loader, memory):
    sections = []

    soul = _read(os.path.join(workspace_dir, "SOUL.md"))
    if soul:
        sections.append(soul)

    identity = _read(os.path.join(workspace_dir, "IDENTITY.md"))
    if identity:
        sections.append(identity)

    active_skills = skill_loader.get_active_skills() if skill_loader else []
    if active_skills:
        lines = ["## Available Skills"]
        for skill in active_skills:
            lines.append(f"- **{skill['name']}**: {skill['description']}")
        sections.append("\n".join(lines))

    notes = await memory.get_notes() if memory else {}
    if notes:
        lines = ["## What you know about the user"]
        for key, value in list(notes.items())[:MAX_NOTES]:
            content = value.get("content", value) if isinstance(value, dict) else value
            lines.append(f"- {key}: {content}")
        sections.append("\n".join(lines))

    sections.append(f"Current time: {datetime.now(timezone.utc).isoformat()}")

    prompt = "\n\n---\n\n".join(sections)

    if len(prompt) > TOKEN_BUDGET * 4:
        logger.warning("system prompt over budget (%d chars), trimming notes", len(prompt))
        sections = sections[:-2] + sections[-1:] if notes else sections
        prompt = "\n\n---\n\n".join(sections)

    return prompt
