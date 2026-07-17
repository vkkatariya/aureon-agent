"""Unified tool registry — merges local skills and MCP servers into one flat list.

The LLM sees one tool list. The registry routes each call to the correct backend:
  - skill_loader.execute_tool() for local doctrine skills
  - mcp_manager.call_tool() for MCP server tools
  - inline handlers for tightly-coupled tools (cron, terminal, file, etc.)

Deduplication: if a tool name appears in both backends, MCP wins (logged as WARN).
"""
import json
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Merges local skill tools + MCP tools + inline tools into one flat list.

    Usage:
        registry = ToolRegistry(skill_loader, mcp_manager)
        registry.register_inline("cron_create", schema, handler)
        tools = registry.get_all()          # → list[dict] for LLM
        result = await registry.dispatch("terminal", args, context)
        backend = registry.get_backend("terminal")  # → "inline"
    """

    def __init__(self, skill_loader=None, mcp_manager=None):
        self.skill_loader = skill_loader
        self.mcp_manager = mcp_manager

        # Inline tool registry: tools tightly coupled to agent state
        # (cron tools, terminal, file, web, todo, clarify, delegate_task)
        self._inline_schemas: dict[str, dict] = {}   # name → schema dict
        self._inline_handlers: dict[str, Callable] = {}  # name → async handler

        # Backend routing cache (rebuilt on refresh)
        self._tool_backend: dict[str, str] = {}  # name → "skill" | "mcp" | "inline"
        self._merged_tools: list[dict] = []

    def register_inline(self, name: str, schema: dict,
                        handler: Callable[..., Awaitable[str]]):
        """Register an inline tool (tightly coupled to agent state).

        Args:
            name: Tool name (e.g. 'terminal', 'cron_create')
            schema: Tool definition dict with 'name', 'description', 'parameters'
            handler: Async callable(args: dict, context: dict) → str
        """
        self._inline_schemas[name] = schema
        self._inline_handlers[name] = handler
        # Invalidate cache
        self._merged_tools = []

    def get_all(self) -> list[dict]:
        """Return the merged tool list for the LLM.

        Merge order (last wins on name collision):
          1. Skill tools (local doctrine)
          2. Inline tools (cron, terminal, etc.)
          3. MCP tools (remote servers)

        MCP tools override skill tools with the same name (WARN logged).
        Inline tools override skill tools (no warning — intentional override).
        """
        if self._merged_tools:
            return self._merged_tools

        by_name: dict[str, dict] = {}
        self._tool_backend = {}

        # 1. Skill tools
        if self.skill_loader:
            for tool in self.skill_loader.get_tools():
                name = tool["name"]
                by_name[name] = tool
                self._tool_backend[name] = "skill"

        # 2. Inline tools (override skills silently — intentional)
        for name, schema in self._inline_schemas.items():
            if name in by_name and self._tool_backend.get(name) == "skill":
                logger.debug("tool '%s': inline overrides skill", name)
            by_name[name] = schema
            self._tool_backend[name] = "inline"

        # 3. MCP tools (override skills with WARNING)
        if self.mcp_manager:
            for tool in self.mcp_manager.get_tools():
                name = tool["name"]
                if name in by_name and self._tool_backend.get(name) == "skill":
                    logger.warning(
                        "tool '%s': MCP server overrides local skill "
                        "(MCP wins on name collision)", name)
                by_name[name] = tool
                self._tool_backend[name] = "mcp"

        # Strip internal MCP metadata from the tool defs sent to LLM
        self._merged_tools = []
        for tool in by_name.values():
            clean = {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"],
            }
            self._merged_tools.append(clean)

        logger.debug("tool registry: %d tools (%d skill, %d inline, %d mcp)",
                      len(self._merged_tools),
                      sum(1 for v in self._tool_backend.values() if v == "skill"),
                      sum(1 for v in self._tool_backend.values() if v == "inline"),
                      sum(1 for v in self._tool_backend.values() if v == "mcp"))

        return self._merged_tools

    async def dispatch(self, name: str, args: dict, context: dict) -> str:
        """Route a tool call to the correct backend.

        Args:
            name: Tool name
            args: Tool arguments dict
            context: Context dict (session_id, memory, etc.)

        Returns:
            Tool result as string (or JSON string for structured results).

        Raises no exceptions — returns error JSON on failure.
        """
        backend = self.get_backend(name)
        logger.debug("dispatch: tool=%s backend=%s", name, backend)

        if backend == "inline":
            handler = self._inline_handlers.get(name)
            if handler:
                return await handler(args, context)
            return json.dumps({"error": f"Inline tool '{name}' has no handler"})

        if backend == "mcp":
            if self.mcp_manager:
                return await self.mcp_manager.call_tool(name, args)
            return json.dumps({"error": "MCP manager not configured"})

        if backend == "skill":
            if self.skill_loader:
                result = await self.skill_loader.execute_tool(name, args, context)
                return json.dumps(result, default=str) if isinstance(result, dict) else str(result)
            return json.dumps({"error": "Skill loader not configured"})

        return json.dumps({"error": f"Unknown tool: {name}"})

    def get_backend(self, name: str) -> str:
        """Return which backend serves a tool: 'skill', 'mcp', 'inline', or 'unknown'."""
        # Ensure cache is populated
        if not self._tool_backend:
            self.get_all()
        return self._tool_backend.get(name, "unknown")

    def refresh(self):
        """Invalidate the cached tool list. Called after skill reload or MCP reconnect."""
        self._merged_tools = []
        self._tool_backend = {}

    @property
    def tool_count(self) -> int:
        return len(self.get_all())

    def list_tools_by_backend(self) -> dict[str, list[str]]:
        """Return tool names grouped by backend. Useful for debugging."""
        self.get_all()  # ensure cache
        result: dict[str, list[str]] = {"skill": [], "inline": [], "mcp": []}
        for name, backend in self._tool_backend.items():
            result.setdefault(backend, []).append(name)
        return result
