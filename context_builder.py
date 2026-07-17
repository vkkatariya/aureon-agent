"""Assembles the system prompt from doctrine files, active skills, and memory notes.

Layered context model (Phase 8, Option B):
- BRAIN layer (always-on, every turn): SOUL + IDENTITY + WORKFLOW + MEMORY + USER
  These are the agent's persistent identity + preference context. Loaded at boot
  in priority order, each wrapped in a labeled section.
- JIT layer (unchanged): skill bodies (on invoke via skill_loader), tasks/todo.md
  (on planning), DEVLOG.md/lessons.md (on debug), SQLite memory notes.

Budget trim protects the BRAIN layer: when over budget, JIT sections are
dropped first, doctrine never trimmed unless absolutely necessary.
"""
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# Rough token budget (chars/4 ≈ tokens). Trimmed if exceeded.
# Raised to 8000 (32K chars ≈ 8K tokens): brain layer (SOUL+IDENTITY+
# WORKFLOW+MEMORY+USER ≈ 25K chars) fits comfortably, leaving headroom
# for JIT (skills menu + notes + time). Trim only triggers if JIT bloats
# or a single brain file is pathologically large.
TOKEN_BUDGET = 8000
MAX_NOTES = 20

# Default brain files (always-on identity/preference layer), priority order.
DEFAULT_BRAIN_FILES = [
    "SOUL.md",
    "IDENTITY.md",
    "WORKFLOW.md",
    "MEMORY.md",
    "USER.md",
]

# Templates / non-brain docs excluded from auto-load.
EXCLUDED_FILES = {
    "MENTAL-MODEL-TEMPLATE.md",  # template only, load on explicit reference
    "CONTEXT.md",                   # dev context, not agent brain
    "AGENTS.md",                    # dev contract, not agent brain
    "CLAUDE.md",                   # dev context, not agent brain
}


@dataclass
class ContextConfig:
    """Config for context assembly. Overridable via env (AUREON_CONTEXT_*)."""
    brain_files: Optional[List[str]] = None
    token_budget: int = TOKEN_BUDGET

    @classmethod
    def from_env(cls) -> "ContextConfig":
        brain = os.getenv("AUREON_CONTEXT_BRAIN_FILES")
        budget = os.getenv("AUREON_CONTEXT_TOKEN_BUDGET")
        return cls(
            brain_files=brain.split(",") if brain else None,
            token_budget=int(budget) if budget else TOKEN_BUDGET,
        )


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""
    except Exception as e:  # noqa: BLE001
        logger.warning("failed to read %s: %s", path, e)
        return ""


def _load_brain(workspace_dir: str, brain_files: List[str]) -> List[str]:
    """Load the always-on identity/preference layer.

    Returns ordered list of labeled sections. Missing files are skipped
    (graceful — partial brain is OK).
    """
    labels = {
        "SOUL.md": "## Soul",
        "IDENTITY.md": "## Identity",
        "WORKFLOW.md": "## Workflow",
        "MEMORY.md": "## Memory",
        "USER.md": "## User",
    }
    sections = []
    for fname in brain_files:
        if fname in EXCLUDED_FILES:
            continue
        content = _read(os.path.join(workspace_dir, fname))
        if content:
            label = labels.get(fname, f"## {fname}")
            sections.append(f"{label}\n\n{content}")
        else:
            logger.debug("brain file missing or empty: %s", fname)
    return sections


async def build_system_prompt(
    workspace_dir,
    skill_loader,
    memory,
    ctx_config: Optional[ContextConfig] = None,
):
    if ctx_config is None:
        ctx_config = ContextConfig.from_env()

    brain_files = ctx_config.brain_files if ctx_config.brain_files is not None else DEFAULT_BRAIN_FILES
    budget = ctx_config.token_budget

    sections = []

    # 1. BRAIN layer (always-on, protected from trim)
    brain = _load_brain(workspace_dir, brain_files)
    sections.extend(brain)

    # 2. JIT layer: active skills menu (names + descriptions only)
    active_skills = skill_loader.get_active_skills() if skill_loader else []
    if active_skills:
        lines = ["## Available Skills"]
        for skill in active_skills:
            lines.append(f"- **{skill['name']}**: {skill['description']}")
        sections.append("\n".join(lines))

    # 3. JIT layer: SQLite memory notes (user knowledge)
    notes = await memory.get_notes() if memory else {}
    if notes:
        lines = ["## What you know about the user"]
        for key, value in list(notes.items())[:MAX_NOTES]:
            content = value.get("content", value) if isinstance(value, dict) else value
            lines.append(f"- {key}: {content}")
        sections.append("\n".join(lines))

    # 4. Current time
    sections.append(f"Current time: {datetime.now(timezone.utc).isoformat()}")

    prompt = "\n\n---\n\n".join(sections)

    # Priority-aware trim: drop JIT sections first (brain protected).
    # JIT sections are everything after the brain block.
    if len(prompt) > budget * 4:
        brain_len = sum(len(s) for s in brain)
        jit = sections[len(brain):]
        logger.warning(
            "system prompt over budget (%d chars), trimming JIT sections first",
            len(prompt),
        )
        # Try dropping JIT one-by-one from the end (time, notes, skills)
        while jit and (brain_len + sum(len(s) for s in jit)) > budget * 4:
            dropped = jit.pop()
            logger.warning("trimmed JIT section (len=%d)", len(dropped))
        if jit:
            prompt = "\n\n---\n\n".join(brain + jit)
        else:
            # Even brain alone over budget — trim brain with WARN, no crash
            logger.error("brain layer alone exceeds budget (%d chars) — truncating", brain_len)
            prompt = "\n\n---\n\n".join(brain)[: budget * 4]

    return prompt
