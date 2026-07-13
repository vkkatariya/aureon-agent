# Task: Add Tier 1 tools (terminal, file, web) to aureon-agent

**Branch:** `feat/aureon-agent-tier1-tools` (off `dev`)
**Mode:** Builder
**Complexity:** Non-trivial — 3 new tools + safety rails + workspace allowlist
**Estimated effort:** 2-3 evenings, ~600-700 LoC + tests

---

## Setup

- **Project:** `aureon-agent`
- **Path on athena:** `~/dev-shared/projects/aureon-agent/`
- **Working directory:** this repo
- **Active branch:** `feat/aureon-agent-tier1-tools` (off `dev`)
- **Session name:** `[aureon-agent]-local` (you're the local session, persistent tmux)

## What this is

Add 3 high-leverage tools to the agent's tool registry, mirroring the shapes Hermes uses for the same capabilities:

- **`terminal`** — run shell commands with allowlist + Captain confirmation for destructive ops
- **`file`** — read/write/list files with workspace allowlist
- **`web`** — web search + fetch (DuckDuckGo HTML for v1, Brave API for v2)

These are the most-leverage missing tools per the tier-1 ranking. Once shipped, the agent can: run shell commands on the user's behalf, manipulate files in approved workspaces, and look things up on the web. Combined with the existing 8 doctrine skills, the agent becomes useful for real work (not just chat).

## Reference docs (read before designing)

- **`skill_loader.py`** — the synthesized tool pattern. Mirror it for each new tool.
- **`agent_runtime.py`** — the ReAct loop where tools are registered + called
- **`~/.openclaw/workspace/MEMORY.md`** §Olympus — channel-policy (per-channel exec ask, security, elevated, destructive)
- **`~/.openclaw/workspace/MEMORY.md`** §🦾 Lessons from 2026-06-16/17 — Captain's hard rules
- **Hermes `terminal` tool** (if you can find docs locally: `~/.npm-global/lib/node_modules/hermes-agent/docs/`) — for shape reference
- **Hermes `web` tool** — DuckDuckGo / Brave backend choices
- **Workspace allowlist:** `~/dev-shared/projects/` (the project root). Captain's standing rule: no writes outside the project tree without explicit confirmation.

## Decisions confirmed with user (2026-07-13)

### Terminal tool
- **Allowlist model:** sandboxed. Captain can pre-approve a set of commands (`ls`, `cat`, `grep`, `find`, `git status`, `git log`, `git diff`) as "auto-run". Anything else requires confirmation.
- **Destructive commands** (`rm`, `mv`, `chmod`, `kill`, `pkill`, `systemctl stop`, `drop`, `delete`, `truncate`, `dd`, `>`, `>>`, `mkfs`, `fdisk`): ALWAYS require Captain confirmation, even if in allowlist.
- **Timeout:** 30 seconds default. Configurable per call.
- **Output capture:** stdout, stderr, exit code. Truncate to 50KB if larger. Return as a structured dict.
- **Working directory:** defaults to the agent's CWD. Can be overridden per call.
- **No shell features:** call `subprocess.run(args, ...)` with a list, not a string. No `shell=True` ever. Prevents injection.
- **No interactive commands:** `vim`, `less`, `top`, `htop`, anything that needs a TTY → return error, not hang.

### File tool
- **Three sub-tools** in the LLM tool registry (Hermes does it this way):
  - `read_file(path: str, max_lines: int = 500) -> str` — returns file content (truncated to `max_lines` if larger)
  - `write_file(path: str, content: str) -> str` — overwrites file (requires Captain confirmation if file exists, no confirm if new file)
  - `list_dir(path: str, pattern: str = "*") -> list[str]` — glob-style listing
- **Allowlist:** paths must start with `~/dev-shared/projects/` OR `~/.openclaw/workspace/` (read-only for the latter). Anything else → error, never silent.
- **No symlink following** outside the allowlist. Resolve symlinks before checking.
- **No binary file writes.** Reject if `path` ends in binary extensions (`.png`, `.jpg`, `.pdf`, `.exe`, `.so`, etc.).
- **Encoding:** always UTF-8. Reject with clear error on decode failure.

### Web tool
- **Two sub-tools:**
  - `web_search(query: str, max_results: int = 5) -> list[dict]` — returns `[{title, url, snippet}]`
  - `web_fetch(url: str, max_chars: int = 5000) -> str` — fetches URL, returns markdown/text content
- **Backend v1:** DuckDuckGo HTML (`https://html.duckduckgo.com/html/?q=...`) for search, direct `httpx` GET for fetch. No API key needed. Privacy-respecting.
- **Backend v2:** Brave Search API (when Captain provides `BRAVE_API_KEY` env, auto-upgrade to API mode).
- **Robots.txt:** respect by default. Captain can disable with `AUREON_WEB_IGNORE_ROBOTS=1` (logged at WARN each call).
- **Blocklist:** local blocklist of known-bad domains (configurable). Default: empty (Captain can add).
- **Timeout:** 10s for search, 30s for fetch.
- **No login / no cookies / no JS execution.** Pure HTTP fetch + HTML parse.
- **User-Agent:** identify as `aureon-agent/0.1 (+https://github.com/vkkatariya/aureon-agent)`.

### Cross-cutting
- **All 3 tools share a common base class** `WorkspaceBoundTool` that enforces the allowlist. Implement once, inherit per-tool.
- **Confirmation flow** uses a single `confirm_with_captain(action: str, summary: str) -> bool` helper that sends a Telegram/Discord message and waits for a reply (timeout 60s, default = no).
- **Audit log** in `data/tool_log.db` (SQLite, append-only): every tool call recorded with timestamp, tool name, inputs (truncated to 1KB), result, exit status, confirmation status.

## Read these on session start (in order)

1. `CLAUDE.md` — project context
2. `CONTEXT.md` — stack, infra, decisions
3. `tasks/DEVLOG.md` (last 2 entries) — current world state
4. `tasks/todo.md` — current phase status
5. This file (the kickoff)
6. `~/.openclaw/workspace/MEMORY.md` §Olympus + §Lessons from 2026-06-16/17
7. `skill_loader.py` — existing tool pattern (mirror)
8. `agent_runtime.py` — ReAct loop (where the tools plug in)

## Your role

You are adding 3 new tool families to the agent's tool registry. Mirror the pattern in `skill_loader.py` (synthesized tool + execute function). Add a `WorkspaceBoundTool` base class for shared allowlist enforcement. Add a `confirm_with_captain()` helper for destructive ops. Self-improvement loop: log every tool call to `workspace/tasks/lessons.md` if it fails in a surprising way.

---

## 6 sub-tasks (in order)

### Sub-task 1: `WorkspaceBoundTool` base class (45 min)

Common allowlist + path validation for all 3 tools.

- [ ] New: `aureon_agent/tools/__init__.py` (empty), `aureon_agent/tools/base.py`, `aureon_agent/tools/confirm.py`, `aureon_agent/tools/log.py`
- [ ] `aureon_agent/tools/base.py`:
  - `class WorkspaceBoundTool` with:
    - `__init__(self, workspace_roots: list[str], readonly_roots: list[str])` — `~/dev-shared/projects/` (read-write), `~/.openclaw/workspace/` (read-only)
    - `def validate_path(self, path: str, write: bool = False) -> Path` — resolves symlinks, checks against allowlist, returns absolute `Path`. Raises `WorkspaceViolation` with clear error.
    - `def is_destructive(self, command: str) -> bool` — for terminal tool, checks if the command matches destructive patterns
- [ ] `aureon_agent/tools/confirm.py`:
  - `async def confirm_with_captain(channel: Channel, action_summary: str, details: str, timeout_sec: int = 60) -> bool` — sends a confirmation message via the channel, waits for `yes`/`no` reply, returns bool. Default = no (deny on timeout).
- [ ] `aureon_agent/tools/log.py`:
  - `class ToolLog: __init__(self, db_path: str = "data/tool_log.db")`
  - Schema: `tool_calls(id, timestamp, session_id, tool_name, inputs_json, result_summary, exit_status, confirmation_status)`
  - `async def record(self, call: ToolCall)` — INSERT
  - `async def list_recent(self, tool_name: str = None, limit: int = 10) -> list[ToolCall]`
- [ ] Tests in `tests/test_tools_base.py`, `tests/test_tools_confirm.py`, `tests/test_tools_log.py`:
  - `validate_path("/etc/passwd")` raises `WorkspaceViolation`
  - `validate_path("~/dev-shared/projects/aureon-agent/main.py")` returns absolute Path
  - `validate_path("~/.openclaw/workspace/SOUL.md", write=True)` raises (read-only)
  - Symlink traversal: `validate_path("~/dev-shared/projects/symlink_to_etc")` raises
  - `is_destructive("rm -rf /")` → True
  - `is_destructive("ls -la")` → False
  - `is_destructive("cat README.md")` → False
  - `confirm_with_captain` timeout → returns False
  - `ToolLog.record` + `list_recent` roundtrip

### Sub-task 2: `terminal` tool (90 min)

- [ ] New: `aureon_agent/tools/terminal.py`
- [ ] `class TerminalTool(WorkspaceBoundTool)` with:
  - Synthesized tool schema:
    ```json
    {
      "name": "terminal",
      "description": "Run a shell command. Auto-run for allowlisted commands (ls, cat, grep, find, git status/log/diff). Destructive commands (rm, mv, kill, etc.) ALWAYS require Captain confirmation. 30s timeout. Working directory defaults to agent CWD.",
      "input_schema": {
        "type": "object",
        "properties": {
          "command": {"type": "string", "description": "Shell command as a list of args, NOT a string (no shell injection)"},
          "cwd": {"type": "string", "description": "Working directory (optional, defaults to agent CWD)"},
          "timeout_sec": {"type": "integer", "default": 30, "maximum": 120}
        },
        "required": ["command"]
      }
    }
    ```
  - `async def execute(self, tool_input: dict, context: dict) -> dict`:
    1. Parse `command` (must be a list, not string — reject if string)
    2. Check `is_destructive(command)` → if True, call `confirm_with_captain` with the command summary
    3. If non-destructive, check against allowlist (whitelist: `ls`, `cat`, `grep`, `find`, `git status/log/diff`, `pwd`, `echo`, `date`, `whoami`, `hostname`, `df`, `du`, `wc`, `head`, `tail`, `which`, `env`)
    4. If non-allowlisted non-destructive → ask Captain (mid-tier: ask once, if approved add to allowlist for the session)
    5. `subprocess.run(args, cwd=cwd, timeout=timeout_sec, capture_output=True, text=True)` — NO `shell=True`
    6. Return `{"stdout": ..., "stderr": ..., "exit_code": ..., "duration_sec": ..., "truncated": bool}`
    7. Truncate stdout/stderr to 50KB if larger
    8. Log to `ToolLog`
- [ ] Register in `agent_runtime.py` alongside the existing synthesized skill tools
- [ ] Tests in `tests/test_tools_terminal.py`:
  - Allowlisted command (`ls -la`) → executes without confirmation
  - Destructive command (`rm -rf /tmp/test`) → asks Captain, returns error if no
  - Non-allowlisted (`curl example.com`) → asks Captain
  - String command (`"ls && rm"`) → rejected (no shell injection)
  - Timeout: command that takes 60s → killed at 30s, returns timeout error
  - Working directory override: `cwd="~/dev-shared/projects/aureon-agent"` works
  - Output truncation: 100KB stdout → truncated to 50KB, `truncated: true`
  - Audit log records the call

### Sub-task 3: `file` tool (90 min)

- [ ] New: `aureon_agent/tools/file.py`
- [ ] `class FileTool(WorkspaceBoundTool)` with 3 sub-tools:
  - `read_file(path, max_lines=500)` — open, read, return content. If file > max_lines, truncate + show line count.
  - `write_file(path, content, overwrite=False)` — open, write, return success. If `overwrite=False` and file exists, ask Captain. Reject binary extensions.
  - `list_dir(path, pattern="*")` — glob, return list of paths
- [ ] `async def execute(self, tool_input: dict, context: dict) -> dict`:
  - Dispatch on `tool_input["action"]` (read/write/list)
  - All paths go through `validate_path` — workspace allowlist enforced
  - For write: if file exists, `confirm_with_captain` with "Overwrite {path}? (current size: {size} bytes)"
  - For binary: detect by extension (`.png`, `.jpg`, `.pdf`, `.exe`, `.so`, `.zip`, `.tar`, `.gz`, `.bin`)
  - For UTF-8: try to decode, raise clear error on failure
- [ ] Synthesized tool schemas (3 separate schemas, dispatch on `action` field)
- [ ] Tests in `tests/test_tools_file.py`:
  - `read_file("README.md")` returns content
  - `read_file("/etc/passwd")` → WorkspaceViolation
  - `write_file("new.txt", "hello")` → creates file, no confirmation (new file)
  - `write_file("existing.txt", "...")` → asks Captain, denied → no write
  - `write_file("image.png", "...")` → rejected (binary)
  - `list_dir("aureon_agent/")` returns list
  - Symlink to /etc → rejected
  - Large file read: 10K line file, max_lines=500 → truncated, returns first 500 + line count

### Sub-task 4: `web` tool (90 min)

- [ ] New: `aureon_agent/tools/web.py`
- [ ] `class WebTool` (no allowlist — public web):
  - `web_search(query, max_results=5)` — DuckDuckGo HTML search
  - `web_fetch(url, max_chars=5000)` — direct httpx GET
- [ ] `web_search` implementation:
  - `httpx.get("https://html.duckduckgo.com/html/", params={"q": query}, headers={"User-Agent": "aureon-agent/0.1"})`
  - Parse HTML with `selectolax` or `beautifulsoup4` — extract `result__a` (title), `result__snippet` (snippet), `result__url` (URL)
  - Return `list[dict]` with `{title, url, snippet}`
  - Handle pagination (DuckDuckGo HTML doesn't paginate, so limit is per-page)
  - Respect `AUREON_WEB_IGNORE_ROBOTS` env
  - Timeout 10s
- [ ] `web_fetch` implementation:
  - `httpx.get(url, headers={"User-Agent": "aureon-agent/0.1"}, follow_redirects=True, timeout=30)`
  - If `content-type` is HTML, convert to text (strip tags, preserve structure)
  - If `content-type` is JSON, return as string
  - Truncate to `max_chars`
  - Reject if status code >= 400 (with the error body)
- [ ] Synthesized tool schemas (2 separate, dispatch on `action`)
- [ ] Tests in `tests/test_tools_web.py`:
  - Mock httpx, verify search query is correct
  - Mock httpx, verify HTML parsing extracts title/URL/snippet
  - `web_fetch("https://example.com")` returns text content
  - `web_fetch("https://httpbin.org/status/500")` returns error
  - Timeout: 60s fetch → killed at 30s
  - Truncation: 100KB content → truncated to 5KB
  - User-Agent header is set correctly

### Sub-task 5: Tool registry integration in `agent_runtime.py` (45 min)

Wire all 3 tools into the ReAct loop.

- [ ] Add to `agent_runtime.py`:
  - On `__init__`: create instances of `TerminalTool`, `FileTool`, `WebTool` with the workspace allowlist
  - In the tool registration: add the synthesized tool schemas from all 3 to the existing skill tool list
  - In the tool dispatch: handle all 3 names (`terminal`, `read_file`/`write_file`/`list_dir`, `web_search`/`web_fetch`)
  - The dispatch should be fast-path: skills are called inline (no subprocess), tools may be (subprocess for terminal, httpx for web)
- [ ] Add a 4th sub-task: per-channel tool policy. Telegram DM can use all 3 (with confirmation flow). Discord DM same. Future: server/group = more restrictive.
- [ ] Tests in `tests/test_agent_loop.py`:
  - All 3 tools are in the agent's tool list when initialized
  - Tool dispatch routes correctly by name
  - Confirmation flow works (mock the channel)

### Sub-task 6: Telemetry + doctor + docs (45 min)

- [ ] Add `aureon-agent tool-log --last 10` subcommand to `aureon_agent/cli.py`
- [ ] Add `aureon-agent tool-log --tool <name>` filter
- [ ] Add `aureon-agent doctor` checks:
  - `data/tool_log.db` is readable
  - workspace allowlist paths exist
  - terminal allowlist is sane
- [ ] Update `CLAUDE.md` Commands section with new subcommand
- [ ] Update `CONTEXT.md` Architecture section to list the 3 new tools
- [ ] Update `README.md` "What it does" section to mention the new tools
- [ ] Add a `docs/tools.md` design doc (matches OpenClaw tool docs style)

## Acceptance criteria

- [ ] `WorkspaceBoundTool.validate_path` enforces `~/dev-shared/projects/` (rw) and `~/.openclaw/workspace/` (ro)
- [ ] Symlinks outside allowlist are rejected
- [ ] `terminal` tool: allowlisted commands run without confirmation
- [ ] `terminal` tool: destructive commands always ask Captain
- [ ] `terminal` tool: string commands rejected (no shell injection)
- [ ] `terminal` tool: 30s timeout kills the subprocess
- [ ] `file` tool: 3 sub-tools (read/write/list) with workspace allowlist
- [ ] `file` tool: binary writes rejected
- [ ] `file` tool: existing file overwrites ask Captain
- [ ] `web` tool: DuckDuckGo search returns list of `{title, url, snippet}`
- [ ] `web` tool: fetch returns text content (HTML stripped) or error
- [ ] All 3 tools log to `data/tool_log.db`
- [ ] `aureon-agent tool-log --last 10` shows recent calls
- [ ] `aureon-agent doctor` checks workspace allowlist
- [ ] All existing tests still pass (no regressions)
- [ ] Live test via Telegram: `ls ~/dev-shared/projects/aureon-agent`, `read README.md`, `search "latest Ollama version"`
- [ ] PR opened to `dev`, DEVLOG entry written, todo.md updated

## Out of scope (v1, will be in Tier 2 follow-up)

- `todo` and `clarify` tools (separate kickoff, separate PR)
- `delegation` subagent tool (already spec'd in `tasks/kickoff-subagent-dispatch.md`)
- `browser` / `computer_use` desktop automation
- `image_gen` / `video_gen` (separate services)
- `spotify` / `homeassistant` / `yuanbao` (services Captain doesn't use)
- Per-command timeout overrides (use the default 30s)
- Background processes (`subprocess.Popen` with daemon mode) — terminal tool waits for completion
- Command history / shell history file
- Real-time streaming output (terminal tool returns all-at-once after completion)
- `web_fetch` JS execution (no Playwright, pure HTTP)
- API mode for web search (Brave API) — DuckDuckGo HTML for v1
- Per-channel tool policy (server/group restrictions) — global policy for v1
- Tool usage analytics / dashboards
- Confirm-timeout tuning (60s default for v1)

## Full spec references

- This file: `tasks/kickoff-tier1-tools.md`
- Doctrine: `~/.openclaw/workspace/MEMORY.md` §Olympus + §Lessons from 2026-06-16/17
- Tool pattern to mirror: `skill_loader.py`
- ReAct loop: `agent_runtime.py`
- Tier 2 follow-up: `tasks/kickoff-tier2-tools.md` (to be written)
- Tier 3 subagent: `tasks/kickoff-subagent-dispatch.md`
