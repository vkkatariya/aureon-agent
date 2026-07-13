# Aureon Agent Tools

The Aureon Agent implements high-leverage tools to augment the LLM's capabilities, mirroring the tools provided by Hermes and OpenClaw.

## Tier 1 Tools

### 1. Terminal Tool (`terminal`)
Allows the agent to run commands in the local shell.
- **Auto-run Allowlist:** Safe read-only commands run instantly (`ls`, `cat`, `grep`, `git status`, etc.)
- **Captain Confirmation:** Destructive commands (`rm`, `mv`, `chmod`, `kill`) pause execution and ask the Captain for explicit approval via the active channel.
- **Safety Rails:** Commands are executed via `subprocess.run(shell=False)` to prevent injection. Max timeout of 30s. Output truncated to 50KB.

### 2. File Tool (`read_file`, `write_file`, `list_dir`)
Allows the agent to explore and modify the workspace.
- **Workspace Bounds:** Operations are strictly limited to `~/dev-shared/projects/` (Read/Write) and `~/.openclaw/workspace/` (Read-only).
- **Binary Rejection:** Refuses to write binary extensions (`.png`, `.exe`, `.pdf`, etc.).
- **Overwrite Protection:** Overwriting an existing file triggers Captain confirmation.

### 3. Web Tool (`web_search`, `web_fetch`)
Grants the agent internet access to research APIs and docs.
- **Search Backend:** Uses DuckDuckGo HTML parsing by default. Can use Brave Search API if `BRAVE_API_KEY` is set.
- **Web Fetch:** Fetches text from any URL using HTTP GET.
- **Robots.txt:** Respected by default unless `AUREON_WEB_IGNORE_ROBOTS=1` is set.

## Tier 2 Tools

### 4. Todo Tool (`todo_read`, `todo_write`, `todo_add`)
Allows the agent to maintain its own plan to satisfy the plan-node requirements.
- **Workspace Bounds:** Operations are strictly limited to `~/dev-shared/projects/` (Read/Write).
- **Format:** Operates on Markdown files, typically `tasks/todo.md`.

### 5. Clarify Tool (`clarify`)
Allows the agent to ask the Captain clarifying questions before executing destructive or ambiguous operations.
- **Loop Pause:** Pauses the ReAct loop and waits for a user response via Telegram/Discord.
- **Caps:** Limited to 1 clarification per iteration and 3 per session to prevent infinite loops.
- **Timeout:** Defaults to 300 seconds. If timed out, returns an empty string to allow the agent to gracefully decide what to do.

## Telemetry and Audit
All tool usages, inputs, and results are logged to an append-only SQLite database at `data/tool_log.db`.

You can view the recent tool usage history by running:
```bash
aureon-agent tool-log --last 10
```
For clarifications specifically:
```bash
aureon-agent clarify-log --last 10
```
