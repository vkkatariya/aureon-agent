"""MCP client — manages connections to MCP servers over stdio transport.

Each MCPClient instance manages one MCP server (one subprocess). The client
handles the full lifecycle: connect → list_tools → call_tool → disconnect.

Tool schemas are translated from MCP format (inputSchema) to OpenAI function
format (parameters) so they merge seamlessly with skill_loader tools.
"""
import json
import logging
import os
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPConfigError(Exception):
    """Raised when MCP server configuration is invalid or server not found."""
    pass


class MCPClient:
    """Manages a single MCP server connection over stdio transport.

    Usage:
        client = MCPClient("notion", command="mcp-server-notion",
                           env={"NOTION_TOKEN": "secret_xxx"})
        await client.connect()
        tools = client.list_tools()       # cached after connect
        result = await client.call_tool("notion_list_pages", {})
        await client.disconnect()
    """

    def __init__(self, server_name: str, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None, prefix: str = "mcp"):
        """
        Args:
            server_name: Unique name for this server (e.g. 'notion', 'github')
            command: Executable to launch (e.g. 'mcp-server-notion', 'npx')
            args: Additional CLI args for the subprocess
            env: Environment variables passed to the subprocess (secrets go here)
            prefix: Tool name prefix (default 'mcp'). Tools become mcp_<server>_<tool>.
        """
        self.server_name = server_name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.prefix = prefix

        self._session: ClientSession | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._tools: list[dict] = []
        self._tool_names: set[str] = set()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def tools(self) -> list[dict]:
        """Return cached tool list (OpenAI function format)."""
        return self._tools

    async def connect(self):
        """Spawn the MCP server subprocess and perform the initialize handshake.

        Raises MCPConfigError if the server binary is not found or handshake fails.
        """
        if self._connected:
            return

        # Build subprocess env: inherit current env + overlay server-specific vars
        child_env = {**os.environ, **self.env}

        server_params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=child_env,
        )

        try:
            self._exit_stack = AsyncExitStack()
            read, write = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            init_result = await self._session.initialize()
            logger.info("MCP server '%s' connected: %s",
                        self.server_name, init_result.server_info if hasattr(init_result, 'server_info') else 'ok')
        except FileNotFoundError:
            raise MCPConfigError(
                f"MCP server binary not found: {self.command!r}. "
                f"Install it or check your PATH."
            )
        except Exception as e:
            # Clean up on partial failure
            if self._exit_stack:
                try:
                    await self._exit_stack.aclose()
                except Exception:
                    pass
                self._exit_stack = None
            raise MCPConfigError(
                f"Failed to connect to MCP server '{self.server_name}': {e}"
            ) from e

        self._connected = True

        # Discover tools
        await self._discover_tools()

    async def _discover_tools(self):
        """Fetch tool list from the server and translate to OpenAI format."""
        try:
            result = await self._session.list_tools()
        except Exception as e:
            logger.error("MCP server '%s': list_tools failed: %s",
                         self.server_name, e)
            self._tools = []
            self._tool_names = set()
            return

        self._tools = []
        self._tool_names = set()

        for tool in result.tools:
            # Prefix tool names to avoid collision with local skills
            prefixed_name = f"{self.prefix}_{self.server_name}_{tool.name}"

            # Translate MCP inputSchema → OpenAI parameters format
            parameters = self._translate_schema(tool.inputSchema) if tool.inputSchema else {
                "type": "object", "properties": {}
            }

            tool_def = {
                "name": prefixed_name,
                "description": tool.description or f"MCP tool: {tool.name}",
                "parameters": parameters,
                # Store the original name for dispatch
                "_mcp_original_name": tool.name,
                "_mcp_server": self.server_name,
            }
            self._tools.append(tool_def)
            self._tool_names.add(prefixed_name)

        logger.info("MCP server '%s': discovered %d tools: %s",
                     self.server_name, len(self._tools),
                     [t["name"] for t in self._tools])

    @staticmethod
    def _translate_schema(input_schema: dict) -> dict:
        """Translate MCP inputSchema to OpenAI-compatible parameters dict.

        MCP inputSchema is already JSON Schema, which is what OpenAI expects.
        We just ensure the top-level has 'type': 'object'.
        """
        schema = dict(input_schema) if input_schema else {}
        if "type" not in schema:
            schema["type"] = "object"
        if "properties" not in schema:
            schema["properties"] = {}
        return schema

    def has_tool(self, name: str) -> bool:
        """Check if this server provides a tool with the given (prefixed) name."""
        return name in self._tool_names

    async def call_tool(self, prefixed_name: str, arguments: dict) -> str:
        """Call a tool on this MCP server.

        Args:
            prefixed_name: The prefixed tool name (e.g. 'mcp_notion_list_pages')
            arguments: Tool arguments dict

        Returns:
            Tool result as string.
            On error, returns JSON string with {"error": "..."}.
        """
        if not self._connected or not self._session:
            return json.dumps({"error": f"MCP server '{self.server_name}' not connected"})

        # Find the original tool name
        original_name = None
        for tool in self._tools:
            if tool["name"] == prefixed_name:
                original_name = tool["_mcp_original_name"]
                break

        if original_name is None:
            return json.dumps({"error": f"Tool '{prefixed_name}' not found on server '{self.server_name}'"})

        try:
            result = await self._session.call_tool(original_name, arguments)

            # Extract text from result content
            parts = []
            for content in result.content:
                if hasattr(content, "text"):
                    parts.append(content.text)
                elif hasattr(content, "data"):
                    parts.append(f"[binary data: {len(content.data)} bytes]")
                else:
                    parts.append(str(content))

            output = "\n".join(parts) if parts else "(empty result)"

            # Check if the server reported an error
            if result.isError:
                return json.dumps({"error": output})

            return output

        except Exception as e:
            logger.error("MCP server '%s': call_tool(%s) failed: %s",
                         self.server_name, original_name, e)
            self._connected = False
            return json.dumps({
                "error": f"MCP server '{self.server_name}' unreachable: {e}"
            })

    async def disconnect(self):
        """Gracefully shut down the MCP server subprocess."""
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                logger.warning("MCP server '%s': disconnect error: %s",
                               self.server_name, e)
            self._exit_stack = None
        self._session = None
        self._connected = False
        self._tools = []
        self._tool_names = set()
        logger.info("MCP server '%s' disconnected", self.server_name)

    async def reconnect(self):
        """Disconnect and reconnect (e.g. after server crash)."""
        await self.disconnect()
        await self.connect()


class MCPManager:
    """Manages multiple MCP server connections.

    Reads server configs and connects to all configured servers at boot.
    Provides a unified interface for tool listing and dispatch.
    """

    def __init__(self):
        self.clients: dict[str, MCPClient] = {}
        self._all_tools: list[dict] = []
        self._tool_to_client: dict[str, str] = {}  # prefixed_name → server_name

    async def add_server(self, server_name: str, command: str,
                         args: list[str] | None = None,
                         env: dict[str, str] | None = None,
                         prefix: str = "mcp") -> bool:
        """Add and connect an MCP server. Returns True if successful."""
        client = MCPClient(server_name, command, args, env, prefix)
        try:
            await client.connect()
            self.clients[server_name] = client
            self._rebuild_tool_index()
            return True
        except MCPConfigError as e:
            logger.warning("MCP server '%s' failed to start: %s", server_name, e)
            return False

    def _rebuild_tool_index(self):
        """Rebuild the merged tool list and routing table."""
        self._all_tools = []
        self._tool_to_client = {}
        for name, client in self.clients.items():
            for tool in client.tools:
                self._all_tools.append(tool)
                self._tool_to_client[tool["name"]] = name

    def get_tools(self) -> list[dict]:
        """Return all MCP tools (OpenAI function format)."""
        return self._all_tools

    def has_tool(self, name: str) -> bool:
        """Check if any MCP server provides this tool."""
        return name in self._tool_to_client

    async def call_tool(self, prefixed_name: str, arguments: dict) -> str:
        """Route a tool call to the correct MCP server."""
        server_name = self._tool_to_client.get(prefixed_name)
        if not server_name or server_name not in self.clients:
            return json.dumps({"error": f"MCP tool '{prefixed_name}' not found"})
        return await self.clients[server_name].call_tool(prefixed_name, arguments)

    async def disconnect_all(self):
        """Disconnect all MCP servers."""
        for client in self.clients.values():
            await client.disconnect()
        self.clients.clear()
        self._all_tools = []
        self._tool_to_client = {}

    @property
    def server_names(self) -> list[str]:
        return list(self.clients.keys())

    @property
    def tool_count(self) -> int:
        return len(self._all_tools)
