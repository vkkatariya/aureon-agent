"""Soft plan-node check: warn (don't block) when a multi-step task starts without a todo.md plan.

v2 will turn this into a hard block per tasks/kickoff-aureon-agent.md Phase 6.
"""
import os

PLAN_KEYWORDS = ("build", "create", "fix", "add", "implement")
WORD_COUNT_THRESHOLD = 50


def needs_plan(user_message):
    lowered = user_message.lower()
    if any(f" {kw} " in f" {lowered} " for kw in PLAN_KEYWORDS):
        return True
    return len(user_message.split()) > WORD_COUNT_THRESHOLD


async def check_plan(workspace_dir, user_message):
    if not needs_plan(user_message):
        return None

    todo_path = os.path.join(workspace_dir, "tasks", "todo.md")
    try:
        with open(todo_path) as f:
            content = f.read().strip()
    except FileNotFoundError:
        content = ""

    if not content:
        return "plan_node_miss: no todo.md plan for 3+ step task"
    return None
