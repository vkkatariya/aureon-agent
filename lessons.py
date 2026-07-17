"""Appends corrections to workspace/tasks/lessons.md (Captain's own copy),
newest entry first under '## Entries', matching the doctrine template at
~/.openclaw/workspace/tasks/lessons.md."""
import asyncio
import os
from datetime import date

_lock = asyncio.Lock()

HEADER = (
    "# Lessons Learned\n\n"
    "Use this format after any user correction or detected mistake. Newest entry first.\n\n"
    "## Entries\n"
)


def _format_entry(context, what_went_wrong, root_cause, prevention_rule, title):
    today = date.today().isoformat()
    short_title = title or (context[:60] + ("…" if len(context) > 60 else ""))
    return (
        f"### {today} — {short_title}\n"
        f"- **Context:** {context}\n"
        f"- **What went wrong:** {what_went_wrong}\n"
        f"- **Root cause:** {root_cause}\n"
        f"- **Prevention rule (actionable):** {prevention_rule}\n"
    )


async def append_lesson(workspace_dir, context, what_went_wrong, root_cause, prevention_rule, title=None):
    path = os.path.join(workspace_dir, "tasks", "lessons.md")
    entry = _format_entry(context, what_went_wrong, root_cause, prevention_rule, title)

    async with _lock:
        existing = ""
        if os.path.exists(path):
            with open(path) as f:
                existing = f.read()

        if "## Entries" in existing:
            head, _, rest = existing.partition("## Entries\n")
            new_content = f"{head}## Entries\n\n{entry}\n{rest.lstrip(chr(10))}"
        else:
            new_content = f"{HEADER}\n{entry}\n"

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(new_content)
