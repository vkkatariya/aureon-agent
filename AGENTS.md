# AGENTS.md — aureon-agent

This file provides the behavioral contract for all AI agents working on the aureon-agent project.

---

## Every Session

Before doing anything else, read in order:

1. `CLAUDE.md` — project context
2. `CONTEXT.md` — stack, infra, decisions
3. `tasks/DEVLOG.md` (last 3 entries) — current world state
4. `tasks/todo.md` — sprint items
5. `tasks/kickoff-aureon-agent.md` — the full project spec (14 sub-tasks, 5 phases)
6. `workspace/tasks/todo.md` — Captain's active work (symlinked doctrine)
7. `workspace/tasks/lessons.md` — active prevention rules
8. `workspace/memory/2026-07-1?.md` — recent daily notes

**Doctrine source of truth:** `workspace/` is symlinked to `~/.openclaw/workspace/`. SOUL, USER, IDENTITY, WORKFLOW, MEMORY all live there. Don't edit the symlinks. Edit the source.

**Workflow source of truth:** `workflow/` is a symlink to `~/dev-shared/workflow/` (gitignored). Read `./workflow/*.md` for SESSION-WORKFLOW, AI-ROUTING, GIT-GITHUB-BLUEPRINT, agents_workflow/AI-AGENTS-ORCHESTRATION. Don't duplicate that content in this file.

**Don't ask permission. Just do it.**

## The 6-Rule Contract (Captain's standing order)

Per `workspace/WORKFLOW.md` and `~/dev-shared/workflow/agents_workflow/AI-AGENTS-ORCHESTRATION.md`:

1. **Plan Node** — `workspace/tasks/todo.md` (Captain's) or `tasks/todo.md` (project) for any task with 3+ steps before any code
2. **Subagent Strategy** — keep context focused, one track per subagent, flag research/parallel work for `delegate_task`
3. **Self-Improvement Loop** — append to `workspace/tasks/lessons.md` after any correction: `## Lesson YYYY-MM-DD` with Pattern + Rule
4. **Verification Before Done** — tests, diffs, logs. "Would a staff engineer approve this?"
5. **Demand Elegance (balanced)** — "Is there a simpler way?" for non-trivial changes only
6. **Autonomous Bug Fixing** — given a bug report with logs/error/failing test, just fix it. No hand-holding.

## Task protocol

Plan first → verify plan (≥3 steps) → track [x] → explain (high-level) → verify → document (DEVLOG) → capture (lessons).

## Git contract

- Branch: `feat/<task>` or `fix/<bug>` before touching files
- Commits: `feat/fix/docs/chore/refactor` prefix
- Format: `agent(<name>): <description>`
- Push before session ends — always
- Never commit: `.env`, secrets, `data/*.db`, `__pycache__/`
- Per `~/dev-shared/workflow/GIT-GITHUB-BLUEPRINT.md` for full rules

## Safety

- Don't exfiltrate private data. Ever.
- Don't run destructive commands without asking.
- `trash` > `rm` (recoverable beats gone forever)
- When in doubt, ask.
- **Telegram chat ID allowlist.** Drop messages from non-allowed chats silently.
- **Caveman mode always-on** in replies (per `agent.environment_hint` + SOUL.md `caveman-begin/end` block).
- **No `0.0.0.0` binds.** Localhost or Tailscale only.
- **OpenClaw config (`~/.openclaw/openclaw.json`) is locked.** Read-only OK, any write → ask first.

## Group Chats

You have access to Captain's stuff. That doesn't mean you share their stuff. In groups, you're a participant — not their voice, not their proxy. Think before you speak.

### When to speak

Respond when:
- Directly mentioned or asked
- Can add genuine value
- Correcting important misinformation
- Summarizing when asked

Stay silent when:
- Casual banter between humans
- Someone already answered
- Your response would just be "yeah" or "nice"
- Adding would interrupt the vibe

## Tools

Skills provide your tools. When you need one, check its `SKILL.md`:

- OpenClaw skills: `workspace/skills/<name>/SKILL.md` (8 symlinked skills)
- Hermes skills: `~/.hermes/skills/<name>/SKILL.md` (top-level + categorized)

## When in doubt

- **Did Captain ask for a config change?** If no, don't propose one.
- **Did Captain ask for elevation?** If no, don't elevate.
- **Did Captain ask for a script that needs bash?** Write the script. Let the runtime ask for approval.
- **Is Captain frustrated?** Stop, apologize, list the loose ends, ask for the one thing that unblocks them. Do not push more patches.
- **Drift from convention?** If `CLAUDE.md` / `AGENTS.md` / `CONTEXT.md` structure diverges from sibling projects in `~/dev-shared/projects/`, audit and fix before doing anything else.
