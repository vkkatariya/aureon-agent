# MCP Integration

aureon-agent supports the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) for connecting to external services. MCP servers expose tools that the agent can use alongside its built-in doctrine skills — the LLM sees one unified tool list.

## Architecture

```
[ Telegram ] [ Discord ]
        \       /
   [ Channel Router ]
              |
   [ Agent Runtime ] ← ReAct loop, MAX_TOOL_ROUNDS=5, Ollama streaming
              |
   [ Tool Registry ] ← merged tool list (skills + inline + MCP)
       /     |     \
      /      |      \
[Skills] [Inline]  [MCP Manager]
 (8 doctrine  (terminal, (N MCP servers
  skills)      file, web,  on demand)
               cron, etc.)
```

## How it works

1. **Boot:** `aureon_agent/cli.py` reads env vars, connects configured MCP servers via `MCPManager`
2. **Tool discovery:** Each MCP server lists its tools via `session.list_tools()`
3. **Schema translation:** MCP `inputSchema` → OpenAI function `parameters` format
4. **Name prefixing:** Tools get prefixed as `mcp_<server>_<tool>` (e.g. `mcp_notion_list_pages`)
5. **Registry merge:** `ToolRegistry` merges skills + inline tools + MCP tools into one flat list
6. **Dispatch:** When the LLM calls a tool, the registry routes to the correct backend
7. **Delivery:** Results flow back through the ReAct loop as tool call responses

## Configuring MCP servers

MCP servers are configured via environment variables in `.env`:

### Notion

```bash
# In .env
NOTION_TOKEN=secret_xxx  # Notion integration token
```

Requires `mcp-server-notion` to be installed:

```bash
npm install -g @anthropic/mcp-server-notion
# or
npx -y @anthropic/mcp-server-notion
```

### GitHub (Phase 7.4, future)

```bash
# In .env
GITHUB_MCP_TOKEN=ghp_xxx  # GitHub personal access token (read-only scope)
```

### Adding a new MCP server

1. Add the env var check to `_parse_mcp_servers()` in `aureon_agent/cli.py`
2. Add the binary check to `check_mcp_servers()` in `aureon_agent/doctor.py`
3. Install the server binary
4. Set the env var in `.env`
5. Restart the bot

## Tool naming convention

| Backend | Example | Format |
|---|---|---|
| Doctrine skills | `read_skill_caveman` | `read_skill_<name>` |
| Inline tools | `terminal`, `cron_create` | Short, lowercase |
| MCP tools | `mcp_notion_list_pages` | `mcp_<server>_<tool>` |

This prevents name collisions. If a name collision occurs (same name in skill + MCP), **MCP wins** and a warning is logged.

## Failure handling

| Scenario | Behavior |
|---|---|
| Server binary not found | `MCPConfigError` at boot → log warning, continue with skills-only |
| Server crashes at boot | Log warning, continue without that server |
| Server crashes mid-session | `call_tool` returns `{"error": "server unreachable"}`, agent surfaces to user |
| Tool call fails | Error message returned to LLM, which can retry or explain |

**No silent failures.** Captain's rule.

## CLI commands

```bash
# List configured MCP servers and their tools
aureon-agent mcp list
```

## Health check

`aureon-agent doctor` includes an "MCP Servers" check:
- 🟡 No MCP servers configured (skills-only mode)
- ✅ N server(s) configured: notion, github
- ❌ Binary missing for: notion

## Security

- **stdio transport only (v1):** Secrets passed via subprocess `env=` param. No network between agent and server.
- **Secrets in `.env`:** chmod 600, never committed to git.
- **Tool confirmation:** MCP tools go through the same ReAct loop as built-in tools. Destructive operations trigger the auto-clarity override.

## Supported transports

| Transport | Status | Use case |
|---|---|---|
| stdio | ✅ v1 | Notion, GitHub, Filesystem — one subprocess per server |
| HTTP/SSE | ⏳ v2 | Gmail (needs OAuth), shared servers on Tailscale |

## Troubleshooting

### MCP server not connecting
- Check `aureon-agent mcp list` — does it show the server?
- Check the env var is set: `echo $NOTION_TOKEN`
- Check the binary is installed: `which mcp-server-notion`
- Check logs: `aureon-agent logs` → look for "MCP server" lines

### Tools not appearing
- MCP tools are prefixed: `mcp_notion_list_pages`, not `list_pages`
- Check `aureon-agent mcp list` for the full tool names
- Run `aureon-agent doctor` to verify the MCP Servers check

### Server crashes mid-session
- The agent will get an error and surface it to the user
- Restart the bot to reconnect: `aureon-agent stop && aureon-agent start`
- Check `aureon-agent logs` for the crash reason
