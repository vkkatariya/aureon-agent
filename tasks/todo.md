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

## Phase 7: MCP integration (keep local skills, add MCP for new services)

**Decision (2026-07-13, Captain's call):** **Keep both registries.** Local OpenClaw skills (SKILL.md + handler.py) stay forever. MCP servers are **additive** for new services only. Agent Runtime merges both tool lists at boot. Gradual migration, zero rewrite of working code.

**Why hybrid, not full migration:**
- OpenClaw skills (caveman, homelab-*, project-init, nano-banana-pro, notion, openclaw-health) already work, audited, doctrine-aware.
- MCP server dependency surface is large — new code to vet per service.
- Two registries is fine until 5+ MCP servers, then reconsider.

**Architecture:**
```
[ Telegram ] [ Discord ]
        \       /
   [ Channel Router ]
              |
   [ Agent Runtime ] ← ReAct loop, MAX_TOOL_ROUNDS=5, Ollama streaming
              |
   [ Tool Registry ] ← merged tool list
       /         \
      /           \
[Skill Loader]   [MCP Client]
  (8 OpenClaw    (N MCP servers
   skills)         on demand)
```

Both backends expose tools to the LLM in the same Anthropic tool-use format. LLM doesn't know or care which backend served the tool.

**Sub-task 15: MCP client + tool registry merger (Phase 7.1)**
- [ ] `mcp_client.py` — connection manager (stdio + HTTP/SSE), graceful failure per server
- [ ] `tool_registry.py` — merge `skill_loader.get_tools()` + `mcp_client.list_tools()` into one flat list
- [ ] Add `mcp` to `requirements.txt`
- [ ] Update `agent_runtime.py` to route tool calls to right backend (skill_loader.execute_tool vs mcp_client.call_tool)
- [ ] Test: 1 OpenClaw skill + 1 MCP server both load, both invokable, no double-registration

**Sub-task 16: First MCP server — Notion (Phase 7.2)**
- [ ] Decide: replace existing `notion` skill (full migration) OR run both (parallel)
- [ ] Recommend: **keep notion skill as fallback, add Notion MCP server as primary** — easy rollback
- [ ] Use official `mcp-server-notion` if available, else community `@gongrzhe/notion-mcp-server`
- [ ] Pass `NOTION_TOKEN` via subprocess env
- [ ] Test: list pages, create page, query database — all via MCP

**Sub-task 17: Gmail MCP server (Phase 7.3)**
- [ ] `gmail-mcp-server` (community) or roll our own
- [ ] OAuth dance: credentials in `~/.openclaw/.env` (chmod 600), refresh token handled by server
- [ ] Deploy as **HTTP/SSE on athena** (Tailscale-only, port 127.0.0.1:N) — shared across agents
- [ ] aureon-agent connects via HTTP, not stdio
- [ ] Test: list inbox, search, send (with explicit confirmation per channel-policy-spec)

**Sub-task 18: GitHub MCP server (Phase 7.4)**
- [ ] Official `@modelcontextprotocol/server-github` via stdio
- [ ] Token in env: `GITHUB_TOKEN` (read-only scope for v1)
- [ ] Use cases: list PRs, read issues, comment on issues (with confirmation)
- [ ] No write operations until Captain explicitly enables

**Sub-task 19: Filesystem MCP server (Phase 7.5)**
- [ ] Official `@modelcontextprotocol/server-filesystem`
- [ ] Sandbox to `~/dev-shared/projects/` only — never `/home/radxa` or `/etc` or `/`
- [ ] Safer than the LLM having raw `bash` access via the homelab skill

**Sub-task 20: Homelab MCP server (Phase 7.6, roll our own)**
- [ ] Wrap existing `homelab-deploy` / `homelab-health` skills as MCP server
- [ ] stdio, one process per agent
- [ ] Lets us retire the skill format for homelab if MCP proves cleaner

**Auth model (per service):**
- **stdio servers:** secrets via subprocess `env=` param. Never touch network between agent and server.
- **HTTP/SSE servers:** secrets live in server process, not agent. Agent just needs URL.
- **Single source of truth:** `~/.openclaw/.env` (chmod 600), env-var refs. Per OpenClaw config lock rule — `openclaw.json` write = ask first.

**Failure handling:**
- MCP server dies at boot → log warning, continue with what loaded (skills-only mode)
- MCP server dies mid-session → tool call returns `{"error": "server unreachable"}`, agent retries once, then surfaces to user
- No silent failure. Captain's rule.

**Migration decision matrix (v2+):**
- 1-2 MCP servers: keep both registries, document the split
- 3-5 MCP servers: consider a thin "tool router" wrapper that hides the split
- 5+ MCP servers: **full migration** to MCP, retire skill format. Only do this when 8+ services exist and the migration cost is justified.

**Phase 7 acceptance criteria:**
- [ ] Tool registry merger works with 0 + 1 + N MCP servers
- [ ] Graceful failure when MCP server unreachable
- [ ] At least 1 real MCP server live (Notion preferred, has clear value)
- [ ] Decision doc in `docs/mcp-decision.md` (why hybrid, when to migrate)
- [ ] Existing 8 OpenClaw skills still load and execute unchanged

