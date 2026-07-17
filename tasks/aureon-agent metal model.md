# Mental model: aureon-agent

## Architecture: aureon-agent vs tiny-openclaw

```
┌─────────────────────────────────────────────────────────────────┐
│ tiny-openclaw (vendored reference, 8 files, 330 LoC)           │
│ • Anthropic-only, JSON file storage                              │
│ • No streaming, no skills, no doctrine, no subagent             │
│ • No subagent dispatch                                           │
│ • One-shot 5-round ReAct, no plan-node                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
                    vendored at references/tiny-openclaw/
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ aureon-agent (production, 2000+ LoC, 11+ modules)                │
│                                                                  │
│  Channels (interface layer)                                     │
│  ┌──────────────────┐  ┌──────────────────┐                       │
│  │ Telegram adapter │  │ Discord adapter  │  ← channels/          │
│  │ (polling, edit)  │  │ (DM-only v1)     │     base.py            │
│  └────────┬─────────┘  └────────┬─────────┘     router.py          │
│           └─────────────────┬──────┘             telegram.py      │
│                             │                    discord.py      │
│  ┌──────────────────────────▼──────────────────────────┐         │
│  │ ChannelRouter  ← pending_confirmations (clarify)   │         │
│  │                ← user reply routing                 │         │
│  └──────────────────────────┬──────────────────────────┘         │
│                             │                                    │
│  Agent Runtime (orchestrator)                                   │
│  ┌──────────────────────────▼──────────────────────────┐         │
│  │ AgentRuntime.run(user_message)                       │         │
│  │   ↓                                                  │         │
│  │ 1. require_plan()  ←── plan_node v2 (hard block)   │         │
│  │   ↓ (if plan OK)                                    │         │
│  │ 2. _maybe_compact() ←── compaction (model-aware)    │         │
│  │   ↓                                                 │         │
│  │ 3. context = ContextBuilder.build(...)              │         │
│  │   ↓                                                 │         │
│  │ 4. ReAct loop (MAX_TOOL_ROUNDS=5):                 │         │
│  │    for tool_call in LLM_response:                   │         │
│  │      tool = tool_registry[tool_name]               │         │
│  │      if tool == clarify: await user reply          │         │
│  │      if tool == delegate_task: spawn subagent      │         │
│  │      else: await tool.execute(tool_input, context) │         │
│  │      if response.confidence >= 0.8: break          │         │
│  │   ↓                                                 │         │
│  │ 5. sessions.add_message(assistant, response)       │         │
│  └──────────────────────────┬──────────────────────────┘         │
│                             │                                    │
│  Tool Registry (13 tools)                                       │
│  ┌──────────────────────────▼──────────────────────────┐         │
│  │ Synthesized tools (registered in agent_runtime):     │         │
│  │   • 8 doctrine skills: read_skill_<name>             │         │
│  │   • terminal        → aureon_agent/tools/terminal.py │         │
│  │   • file            → aureon_agent/tools/file.py     │         │
│  │   • web             → aureon_agent/tools/web.py      │         │
│  │   • todo_read/write/add → aureon_agent/tools/todo.py  │         │
│  │   • clarify         → aureon_agent/tools/clarify.py  │         │
│  │   • delegate_task   → aureon_agent/subagent/tool.py │         │
│  └─────────────────────────────────────────────────────┘         │
│                                                                  │
│  Storage (persistence layer)                                     │
│  ┌─────────────────────────────────────────────────────┐         │
│  │ data/sessions.db         (aiosqlite WAL)             │         │
│  │   messages: full history, never rewritten            │         │
│  │ data/memory.db           (aiosqlite WAL)             │         │
│  │   note:* namespace (key-value)                      │         │
│  │ data/compaction_log.db   (aiosqlite append-only)     │         │
│  │   compaction_runs: when, tokens, summary, model     │         │
│  │ data/tool_log.db         (aiosqlite append-only)     │         │
│  │   tool_calls: tool, inputs, result, confirmation   │         │
│  │ data/subagent_log.db     (aiosqlite append-only)     │         │
│  │   dispatch_log: task, backend, tokens, result       │         │
│  │ ~/.cache/aureon-agent.pid  (PID lock)                │         │
│  └─────────────────────────────────────────────────────┘         │
│                                                                  │
│  Doctrine (linked, not copied)                                   │
│  ┌─────────────────────────────────────────────────────┐         │
│  │ workspace/  →  ~/.openclaw/workspace/  (symlinks)    │         │
│  │   SOUL.md, USER.md, IDENTITY.md, WORKFLOW.md,         │         │
│  │   MENTAL-MODEL-TEMPLATE.md, MEMORY.md, HEARTBEAT.md,  │         │
│  │   channel-policy-spec.md, handoff-template.md,        │         │
│  │   skills/, memory/                                  │         │
│  │                                                   │         │
│  │ workflow/  →  ~/dev-shared/workflow/  (gitignored)   │         │
│  └─────────────────────────────────────────────────────┘         │
│                                                                  │
│  CLI (operator surface)                                          │
│  ┌─────────────────────────────────────────────────────┐         │
│  │ aureon-agent        → python -m aureon_agent          │         │
│  │   setup | postinstall | doctor | start | stop |     │         │
│  │   status | logs | version | help                    │         │
│  │ aureon-agent-setup  → aureon_agent.setup:main        │         │
│  │ aureon-agent-doctor → aureon_agent.doctor:main       │         │
│  │ aureon-agent-postinstall → aureon_agent.postinstall  │         │
│  │                                                     │         │
│  │ Subcommands (registered in __main__.py):            │         │
│  │   tool-log --last 10 [--tool <name>]                │         │
│  │   clarify-log --last 10 [--session <id>]            │         │
│  │   subagent-log --last 10 [--backend <type>]         │         │
│  │   compaction-log --last 10 [--session|--model]       │         │
│  └─────────────────────────────────────────────────────┘         │
│                                                                  │
│  Process management                                              │
│  ┌─────────────────────────────────────────────────────┐         │
│  │ systemd user service (PID 2372177)                  │         │
│  │   ~/.config/systemd/user/aureon-agent.service       │         │
│  │   Restart=on-failure, RestartSec=10                 │         │
│  │   loginctl enable-linger  (survives logout)         │         │
│  │   PID lock at ~/.cache/aureon-agent.pid             │         │
│  │   (prevents Telegram 409 from two instances)         │         │
│  └─────────────────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

---

## The 13 tools in detail

### 8 doctrine skills (prose-only, all auto-loaded from `workspace/skills/`)

Each is one synthesized tool `read_skill_<name>` that returns the SKILL.md body on demand:

| Tool | Purpose | Trigger |
|---|---|---|
| `read_skill_caveman` | Compressed reply mode (~75% token savings) | Auto-applied via `agent.environment_hint` |
| `read_skill_homelab-deploy` | Tailscale sidecar deploy pattern | When Captain mentions deploy |
| `read_skill_homelab-health` | Health check homelab services | When Captain mentions health |
| `read_skill_homelab-scaffold` | New service from template | When Captain mentions scaffold |
| `read_skill_nano-banana-pro` | Image generation (Google) | When Captain wants an image |
| `read_skill_notion` | Read/write Notion (deprecated) | When Captain mentions Notion |
| `read_skill_openclaw-health` | Check OpenClaw agent integrity | When Captain mentions doctrine |
| `read_skill_project-init` | New project dev setup | When Captain starts a project |

### 5 active tools (real Python execution, registered in `agent_runtime.py`)

| Tool | File | What it does | Safety rails |
|---|---|---|---|
| `terminal` | `tools/terminal.py` | Run shell commands | Allowlist + Captain confirm for destructive, no `shell=True`, 30s timeout, 50KB output cap |
| `file` | `tools/file.py` | 3 sub-tools: `read_file`/`write_file`/`list_dir` | `WorkspaceBoundTool` allowlist, binary rejected, UTF-8, Captain confirm for overwrite |
| `web` | `tools/web.py` | `web_search` (DuckDuckGo) + `web_fetch` (httpx) | Robots.txt respected, 10s/30s timeouts, UA header |
| `todo` | `tools/todo.py` | 3 sub-tools: `todo_read`/`todo_write`/`todo_add` | Workspace allowlist, Markdown format |
| `clarify` | `tools/clarify.py` | Pause ReAct, ask Captain, resume | 1-per-iteration cap, 3-per-session cap, 5min timeout, channel router routes reply |
| `delegate_task` | `subagent/tool.py` | Spawn claude-code subprocess for parallel work | Sandbox in `/tmp/aureon-subagent-<uuid8>/`, 50K token cost control, 5min timeout, audit log |

Total: **13 tools** (5 active + 8 doctrine).

---

## How a Telegram message flows end-to-end

```
1. Captain sends "build X, test Y, deploy Z" to @aureon_agent_bot

2. Telegram → POST https://api.telegram.org/bot<TOKEN>/getUpdates
   (polled every ~10s by the bot's running process)

3. channels/telegram.py receives update, extracts (chat_id, text)

4. channels/router.py:handle_message() called
   - Check pending_confirmations: nothing pending → proceed normally
   - sessions.get_or_create_session(client_id="telegram:723865496")
   - sessions.add_message("user", text)
   - register callback: agent_runtime.handle_message(...)

5. agent_runtime.run(user_message):
   a) require_plan(workspace_dir, user_message)
      - count_features("build X, test Y, deploy Z") = 3 (verbs: build, test, deploy)
      - has_plan(".") = False (no - [ ] in tasks/todo.md)
      - returns (ok=False, reason="plan_node_block: 3+ step task, no plan")
      - LOG: plan_node_blocks_total++
      - SKIP to step 5b (return error to user)

   b) Telegram reply: "🛑 Plan needed. Add a plan or say 'just do it' to bypass."

6. Captain: "add a plan: - [ ] build X"  → added via todo_add tool
   Captain: "just do it"                     → bypass phrase

7. agent_runtime.run("build X, test Y, deploy Z, just do it") (second call):
   a) require_plan():
      - detect "just do it" → bypass, log WARN
      - returns (ok=True, reason=None)
   b) _maybe_compact(history, system_prompt):
      - system_prompt_tokens = 2500
      - compact_threshold = 32768 - 4096 - 2500 = 26172
      - history_tokens = 15000 → no compaction (under threshold)
   c) ContextBuilder.build():
      - SOUL.md (caveman mode) + IDENTITY.md (4 modes) + 8 doctrine skills
      - note:* memory entries
      - system_prompt = ~2.5K tokens
   d) ReAct loop (5 rounds max):
      Round 1: LLM returns tool_call={"name": "terminal", "args": ["ls", "-la"]}
        - tool.execute() → subprocess.run(["ls", "-la"], timeout=30)
        - returns {"stdout": "...", "exit_code": 0, "duration_sec": 0.05}
      Round 2: LLM returns text response
        - early exit (no more tool calls)
   e) sessions.add_message("assistant", response)
   f) channels/telegram.py edits message in-place via editMessageText
      (throttled to 1/sec)
```

That's one Captain message → one Telegram reply. Total time: ~1-3 sec.

---

## The 4 Phase 6.5 work items, in plain English

### Tier 1: terminal + file + web
**Problem:** Bot could only chat. Couldn't run commands, read/write files, or look things up.
**Fix:** 3 tools with workspace allowlist. The `WorkspaceBoundTool` base class enforces that all paths are inside `~/dev-shared/projects/` (read-write) or `~/.openclaw/workspace/` (read-only). Anything else → error.
**Why it matters:** Captain can now ask the bot to actually do things, not just talk.

### Tier 2: todo + clarify
**Problem:** Bot couldn't plan or ask.
**Fix:**
- `todo` tool: 3 sub-tools to manage `tasks/todo.md` plan files. The agent can write its own plan.
- `clarify` tool: pause the ReAct loop, send a question to Captain via Telegram, wait for the reply, resume with the answer in the LLM's context. 1-clarify-per-iteration + 3-clarify-per-session caps prevent infinite clarification loops.
**Why it matters:** Bot can now plan, ask, and proceed with consent. Closes the loop with the plan-node hard block.

### Tier 3: subagent dispatch (`delegate_task`)
**Problem:** Bot can only do simple things in-line. Long tasks would block the chat.
**Fix:** When the LLM calls `delegate_task`, the agent shells out to a `claude-code` CLI subprocess in a sandbox (`/tmp/aureon-subagent-<uuid8/` with a copy of the workspace). The subagent does the work, returns a JSON summary + diff, and the parent bot reports back to Captain.
**Why it matters:** Bot can now spawn parallel work. Code reviews, long research, multi-file refactors — all offloaded to a subagent that won't block the Telegram chat.

### Tier 4: plan-node hard block (v2)
**Problem:** Bot would start any task without checking for a plan. "I'll just add this one thing" → scope creep → 4-hour rabbit hole.
**Fix:** `plan_node.py` now uses a feature counter (imperative verbs, conjunctions, URLs, file paths). 3+ features → hard block with a clear Telegram message. Read-only requests bypass. Magic phrases ("just do it") bypass with WARN log.
**Why it matters:** Bot is now forced to ask Captain before doing dangerous work. Pairs with `clarify` (Captain can write a plan in-line via the chat).

---

## The 4 SQLite databases

| DB | Schema | Purpose | Never modified? |
|---|---|---|---|
| `data/sessions.db` | `messages(id, session_id, role, content, created_at)` | Conversation history | **Yes** — view-layer only |
| `data/memory.db` | `memory(key TEXT PK, value TEXT, updated_at)` | Key-value with `note:*` namespace | No (intentional) |
| `data/compaction_log.db` | `compaction_runs(...)` | Audit: when, tokens, summary, model | Append-only |
| `data/tool_log.db` | `tool_calls(...)` | Audit: every tool call | Append-only |
| `data/subagent_log.db` | `dispatch_log(...)` | Audit: every subagent dispatch | Append-only |

The 3 audit logs are append-only so Captain can always trace what the bot did, even if the LLM context is later compacted or the session is wiped.

---

## The process model

**Two ways to run:**

1. **Foreground (development):** `python -m aureon_agent` or `aureon-agent start`
2. **Background (production):** systemd user service, PID file at `~/.cache/aureon-agent.pid`

**Why systemd:**
- Auto-restart on crash (`Restart=on-failure`, `RestartSec=10`)
- Survives logout (`loginctl enable-linger`)
- Survives reboot (`WantedBy=default.target`)
- Logs in journald (`journalctl --user -u aureon-agent.service -f`)
- The PID lock at `~/.cache/aureon-agent.pid` prevents two instances from running (which causes Telegram 409 Conflict errors)

**Doctor status check** (current state):
- 7/8 green checks (Python version, venv, .env perms, workspace symlinks, tools allowlist, Claude CLI, plan node, Ollama, Telegram API, smoke tests)
- 1 🟡 expected warning: systemd status (the sub-process doesn't have DBUS, can't see systemd)

---

## The compile-time check (what runs on every Telegram message)

When a Telegram update arrives, the bot does these checks in order:

1. **PID lock** — `acquire_lock()` on `~/.cache/aureon-agent.pid`. If another instance holds it, exit 1.
2. **Plan-node check** — `require_plan(workspace, message)`. If 3+ step task without plan, return error.
3. **Compaction check** — `_maybe_compact(history, system_prompt)`. If history > threshold, summarize old turns. Off by default.
4. **Context build** — assemble system prompt from SOUL + IDENTITY + skills + memory + time.
5. **ReAct loop** — call LLM, parse response, dispatch tools, loop up to 5 rounds.
6. **Tool dispatch** — route to the right tool (synthesized or one of the 5 active). For `clarify`, pause. For `delegate_task`, spawn subprocess.
7. **Session write** — append Captain's turn + bot's response to `data/sessions.db`.
8. **Audit log** — every tool call, compaction, dispatch goes to the respective audit log.
9. **Reply** — Telegram `editMessageText` (1/sec throttle).

---

## What's NOT in v1 (still pending)

- Live-Telegram round-trip tests for compaction (deferred — needs real chat context)
- Webhook mode for Telegram (replace polling)
- Server/group channel support (per-channel tool policy)
- Phase 7: MCP integration (Notion, Gmail, GitHub) — kickoff in `tasks/kickoff.md`
- Doctor warning: systemd status in sub-process context (cosmetic)

---

## Files you'd touch if you want to extend

| Want to... | Edit |
|---|---|
| Add a new tool | Create `aureon_agent/tools/<name>.py`, inherit `WorkspaceBoundTool`, register in `agent_runtime.py` |
| Add a new doctrine skill | Drop a `SKILL.md` in `~/.openclaw/workspace/skills/<name>/`, restart bot (or hot-reload picks it up) |
| Change session compaction | Edit `aureon_agent/models.py` (context windows) or `compaction/threshold.py` (formula) |
| Add MCP server | New `mcp_client.py`, register in `agent_runtime.py` (per Phase 7 plan) |
| Change bot identity | Edit files in `~/.openclaw/workspace/` (SOUL.md, IDENTITY.md, etc.) — symlinked, not in repo |
| Change LLM provider | Edit `aureon_agent/cli.py` + `AureonConfig` in `aureon_agent/config.py` |

---

## The 5 lessons learned (full list in `tasks/lessons.md`)

1. **"Shipped" doesn't mean "in dev"** — verify with `git log origin/<branch>..dev`. Captain's report said plan-node was shipped; it was on the remote branch but not in dev.
2. **Agent's subagent work introduced `NameError`** — `check_claude_cli()` used `shutil.which()` but didn't import `shutil`. Always check imports when adding a new function.
3. **Don't mark todo.md done before git verification** — same root cause as #1.
4. **Cherry-pick can lose content** — when picking from a branch, check the parent's tree state. Source branch's content not in target's tree = content lost.
5. **Python doesn't auto-import stdlib** — `shutil.which()` requires `import shutil`. Use `ruff check` in CI to catch this.

---

## TL;DR

aureon-agent is a Hermes-flavored autonomous AI agent that:
- Lives on athena, runs as a systemd user service
- Talks to Captain on Telegram (Discord ready, untested)
- Loads doctrine from symlinked `~/.openclaw/workspace/`
- Has 13 tools: 8 doctrine skills + 5 active tools (terminal, file, web, todo, clarify, delegate_task)
- Blocks 3+ step tasks without a plan, asks clarifying questions
- Spawns subagents for parallel work
- Compacts long sessions to stay within model context
- Audits every action to 3 separate SQLite logs
- Never loses the conversation history (view-layer compaction only)

It's significantly more capable than tiny-openclaw (which it was originally modeled on) and now has parity with most of Hermes's 23 built-in toolsets. The remaining gap is the deferred work (live tests, MCP, server channels).

Sleep well. aureon-agent is humming along under systemd.
