import os
from datetime import datetime, timezone

BASE_PROMPT = """You are a helpful personal AI assistant powered by Tiny OpenClaw.
Be concise, friendly, and helpful. Use tools when they would help."""

# Load SOUL.md
def load_soul():
    # Path to SOUL.md
    soul_path = os.path.join(os.path.dirname(__file__), "SOUL.md")
    
    # Open the file
    try:
        with open(soul_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return BASE_PROMPT

# Combine Soul.md, Skills, User memory and Current time into a System prompt
def build_system_prompt(active_skills, memory=None):
    prompt = load_soul() # Load SOUL.md

    # Add name and descriptions of available Skills
    if active_skills:
        prompt += "\n\n## Available Skills\n"
        for skill in active_skills:
            prompt += f"### {skill['name']}\n"
            prompt += f"{skill['description']}\n\n"

    # Add details from saved memory about the user
    if memory:
        prefix = "note:"
        notes = {
            k[len(prefix):]: memory.get(k)
            for k in memory.keys()
            if k.startswith(prefix)
        }

        if notes:
            prompt += "\n\n## What you know about the user\n"
            for key, value in notes.items():
                content = value.get("content", value) if isinstance(value, dict) else value
                prompt += f"- {key}: {content}\n"

    # Add current time
    prompt += f"\nCurrent time: {datetime.now(timezone.utc).isoformat()}"

    return prompt