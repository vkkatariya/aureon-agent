# aureon-agent — Tasks

## Phase 0: Setup ✅
- [x] Workspace symlinks to ~/.openclaw/workspace/ (SOUL, USER, IDENTITY, WORKFLOW, MENTAL-MODEL, MEMORY, skills/, memory/)
- [x] AGENTS.md (6-rule per-project contract)
- [x] CONTEXT.md (stack, infra, decision log)
- [x] README.md (setup, env, run, workspace restore)
- [x] CLAUDE.md (Claude Code session context)
- [x] .gitignore (env, db, cache, openclaw scratch)
- [x] requirements.txt (httpx, python-telegram-bot, discord.py, aiosqlite, watchfiles, aiohttp, python-dotenv)
- [x] tasks/kickoff-aureon-agent.md (14 sub-tasks, 5 phases)
- [x] GitHub repo created (public)
- [x] CI pipeline active (Python 3.12, pip install -r requirements.txt, smoke tests)
- [x] dev branch created and pushed

## Phase 1: Workspace + doctrine (foundation) ✅
- [x] Sub-task 1: Workspace symlinks (all 11 wired to ~/.openclaw/workspace/)
- [x] Sub-task 2: Project bootstrap files (AGENTS.md, CONTEXT.md, AGENTS.md, README.md, .gitignore, requirements.txt)

## Phase 2: Core runtime (Tiny-OpenClaw ports)
- [ ] Sub-task 3: Memory + Session (SQLite) — aiosqlite, WAL mode, asyncio.Lock per session_id
- [ ] Sub-task 4: Skill loader (OpenClaw format) — parse SKILL.md frontmatter, watchfiles hot-reload
- [ ] Sub-task 5: Context builder (doctrine-aware) — load SOUL/IDENTITY/skills/note:* + time, <2K tokens
- [ ] Sub-task 6: Agent runtime (Ollama + streaming + plan-node soft check) — ReAct loop, MAX_TOOL_ROUNDS=5, caveman in replies, auto-clarity

## Phase 3: Channel adapters (multi-channel)
- [ ] Sub-task 7: Channel ABC + Router
- [ ] Sub-task 8: Telegram adapter (python-telegram-bot, chat ID allowlist, streaming editMessageText)
- [ ] Sub-task 9: Discord adapter (discord.py, DM-only, streaming message.edit)

## Phase 4: Entry + integration
- [ ] Sub-task 10: main.py (env load, wire all 7, SIGTERM, health endpoint)
- [ ] Sub-task 11: Plan-node module (soft-warning helper)
- [ ] Sub-task 12: Lessons writer (append to workspace/tasks/lessons.md)

## Phase 5: Verification
- [ ] Sub-task 13: Smoke tests (skill load, DB roundtrip, context builder, agent loop)
- [ ] Sub-task 14: Dev workflow docs (README update, DEVLOG, root ~/dev-shared/notes link)

## Phase 6: Production hardening (post-MVP)
- [ ] systemd user service at ~/.config/systemd/user/aureon-agent.service
- [ ] Plan-node hard block (v2)
- [ ] Subagent dispatch via Hermes delegate_task
- [ ] Session compaction for long histories
- [ ] Webhook mode for Telegram (replace polling)
- [ ] Server/group channel support
