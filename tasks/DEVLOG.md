# Dev Log
> Append-only. Agents write an entry at the end of every session. Newest at top.

---

## 2026-07-13 init — Hermes project-init skill (partial)
**Did:** Created full project dev setup for aureon-agent
**Stack:** Python 3.12 + httpx + aiosqlite + python-telegram-bot + discord.py + Ollama (local + cloud)
**Infra:** athena (single Python process, Tailscale, no Docker, no 0.0.0.0 binds)
**State:** Bootstrap files (AGENTS.md, CONTEXT.md, README.md, CLAUDE.md, .gitignore, requirements.txt, kickoff spec) pre-existed from prior Hermes bootstrap. Added the 4 missing skill-required files (tasks/DEVLOG.md, tasks/todo.md, tasks/lessons.md, .github/workflows/ci.yml). Workspace symlinks to ~/.openclaw/workspace/ doctrine already wired. Git initialized, GitHub repo live, CI pipeline active.
**Decided:** Public GitHub repo (open-source from day 1). `main` + `dev` branch model per skill. Reuse existing AGENTS.md/CONTEXT.md/README.md from prior bootstrap (don't regenerate — per skill partial-setup rules).
**Next:** Phase 1 sub-tasks 1-2 from tasks/kickoff-aureon-agent.md (workspace symlinks + bootstrap already done, so jump to sub-task 3: SQLite Memory + SessionManager).
**Modified:** tasks/DEVLOG.md, tasks/todo.md, tasks/lessons.md, .github/workflows/ci.yml, .git/ (init), origin/main (push), origin/dev (push)
