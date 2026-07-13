# CLAUDE.md — aureon-agent

This file provides guidance to Claude Code (claude.ai/code) when working on this repository.

---

## Session startup

Before any meaningful work, read these in order:

1. `CONTEXT.md` — stack, infra, design tokens
2. `tasks/DEVLOG.md` (last 3 entries) — current world state
3. `tasks/todo.md` — sprint items
4. `tasks/lessons.md` — active prevention rules
5. `tasks/kickoff-aureon-agent.md` — the full spec for this project

**This project is a Python agent.** The detailed kickoff lives in `tasks/kickoff-aureon-agent.md`. Read it first.

**Doctrine source of truth:** `workspace/` contains symlinks to `~/.openclaw/workspace/`. SOUL, USER, IDENTITY, WORKFLOW, MEMORY all live there. Edit those, not the symlinks. If symlinks are broken (fresh clone), see `README.md` §"Workspace" for restore.

## The OpenClaw doctrine (6-rule per-project contract)

Every agent working on this project must follow:

1. **Plan Node** — `workspace/tasks/todo.md` for any task with 3+ steps before any code
2. **Subagent Strategy** — keep context focused, one track per subagent, flag research/parallel work for dispatch
3. **Self-Improvement Loop** — append to `workspace/tasks/lessons.md` after any correction: `## Lesson YYYY-MM-DD` with Pattern + Rule
4. **Verification Before Done** — tests, diffs, logs. "Would a staff engineer approve this?"
5. **Demand Elegance (balanced)** — "Is there a simpler way?" for non-trivial changes only
6. **Autonomous Bug Fixing** — given a bug report with logs/error/failing test, just fix it. No hand-holding.

## Git contract

- Branch: `feat/<task>` or `fix/<bug>` before touching files
- Commits: `feat/fix/docs/chore/refactor` prefix
- Format: `agent(<name>): <description>`
- Push before session ends — always
- Never commit: `.env`, secrets, `data/*.db`, `__pycache__/`

## Session flow (after doctrine loaded)

1. Read `workspace/memory/2026-07-1?.md` (today + yesterday) for recent context
2. Read `workspace/MEMORY.md` if main session (Captain direct chat) — Olympus orchestration, agent roster, lessons
3. Read `workspace/tasks/todo.md` (Captain's own, symlinked) for active work
4. Then begin work

## Compaction + session resume

- Write in-flight state to `tasks/DEVLOG.md` before `/compact` or session end
- After resume: re-read top 3 of DEVLOG, re-read this file, check `git status`
- Cross-session coordination via git branches + PRs + DEVLOG (no separate lineage branches)
