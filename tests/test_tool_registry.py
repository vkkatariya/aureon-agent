"""Tests for the unified tool registry.

Tests cover:
  - Merging skills + inline + MCP tools
  - Deduplication (MCP wins on collision)
  - Dispatch routing to correct backend
  - Backend identification
  - Refresh / cache invalidation
"""
import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestToolRegistryMerge(unittest.TestCase):
    """Test tool list merging from multiple backends."""

    def test_skills_only(self):
        from aureon_agent.tool_registry import ToolRegistry

        mock_skills = MagicMock()
        mock_skills.get_tools.return_value = [
            {"name": "read_skill_caveman", "description": "Read caveman", "parameters": {}},
            {"name": "read_skill_homelab", "description": "Read homelab", "parameters": {}},
        ]

        registry = ToolRegistry(skill_loader=mock_skills)
        tools = registry.get_all()
        self.assertEqual(len(tools), 2)
        self.assertEqual(registry.get_backend("read_skill_caveman"), "skill")

    def test_inline_tools(self):
        from aureon_agent.tool_registry import ToolRegistry

        registry = ToolRegistry()

        async def handler(args, ctx):
            return "ok"

        registry.register_inline("terminal", {
            "name": "terminal",
            "description": "Run command",
            "parameters": {},
        }, handler)

        tools = registry.get_all()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "terminal")
        self.assertEqual(registry.get_backend("terminal"), "inline")

    def test_mcp_tools(self):
        from aureon_agent.tool_registry import ToolRegistry

        mock_mcp = MagicMock()
        mock_mcp.get_tools.return_value = [
            {"name": "mcp_notion_list_pages", "description": "List pages",
             "parameters": {}, "_mcp_original_name": "list_pages", "_mcp_server": "notion"},
        ]

        registry = ToolRegistry(mcp_manager=mock_mcp)
        tools = registry.get_all()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "mcp_notion_list_pages")
        self.assertEqual(registry.get_backend("mcp_notion_list_pages"), "mcp")

    def test_merged_all_backends(self):
        from aureon_agent.tool_registry import ToolRegistry

        mock_skills = MagicMock()
        mock_skills.get_tools.return_value = [
            {"name": "read_skill_caveman", "description": "Caveman", "parameters": {}},
        ]

        mock_mcp = MagicMock()
        mock_mcp.get_tools.return_value = [
            {"name": "mcp_notion_list", "description": "List", "parameters": {},
             "_mcp_original_name": "list", "_mcp_server": "notion"},
        ]

        registry = ToolRegistry(skill_loader=mock_skills, mcp_manager=mock_mcp)

        async def handler(args, ctx):
            return "ok"

        registry.register_inline("terminal", {
            "name": "terminal",
            "description": "Terminal",
            "parameters": {},
        }, handler)

        tools = registry.get_all()
        self.assertEqual(len(tools), 3)

        backends = registry.list_tools_by_backend()
        self.assertEqual(len(backends["skill"]), 1)
        self.assertEqual(len(backends["inline"]), 1)
        self.assertEqual(len(backends["mcp"]), 1)

    def test_mcp_overrides_skill_on_collision(self):
        from aureon_agent.tool_registry import ToolRegistry

        mock_skills = MagicMock()
        mock_skills.get_tools.return_value = [
            {"name": "notion_search", "description": "Skill version", "parameters": {}},
        ]

        mock_mcp = MagicMock()
        mock_mcp.get_tools.return_value = [
            {"name": "notion_search", "description": "MCP version", "parameters": {},
             "_mcp_original_name": "search", "_mcp_server": "notion"},
        ]

        registry = ToolRegistry(skill_loader=mock_skills, mcp_manager=mock_mcp)
        tools = registry.get_all()

        # Only 1 tool (deduplicated)
        self.assertEqual(len(tools), 1)
        # MCP wins
        self.assertEqual(tools[0]["description"], "MCP version")
        self.assertEqual(registry.get_backend("notion_search"), "mcp")

    def test_internal_metadata_stripped(self):
        from aureon_agent.tool_registry import ToolRegistry

        mock_mcp = MagicMock()
        mock_mcp.get_tools.return_value = [
            {"name": "mcp_notion_list", "description": "List", "parameters": {},
             "_mcp_original_name": "list", "_mcp_server": "notion"},
        ]

        registry = ToolRegistry(mcp_manager=mock_mcp)
        tools = registry.get_all()

        # Internal MCP metadata should be stripped from tool defs sent to LLM
        self.assertNotIn("_mcp_original_name", tools[0])
        self.assertNotIn("_mcp_server", tools[0])


class TestToolRegistryDispatch(unittest.TestCase):
    """Test tool call routing to correct backends."""

    def test_dispatch_inline(self):
        from aureon_agent.tool_registry import ToolRegistry

        async def _test():
            registry = ToolRegistry()

            async def my_handler(args, ctx):
                return f"handled: {args.get('cmd')}"

            registry.register_inline("terminal", {
                "name": "terminal",
                "description": "Terminal",
                "parameters": {},
            }, my_handler)

            result = await registry.dispatch("terminal", {"cmd": "ls"}, {})
            self.assertEqual(result, "handled: ls")

        asyncio.run(_test())

    def test_dispatch_mcp(self):
        from aureon_agent.tool_registry import ToolRegistry

        async def _test():
            mock_mcp = MagicMock()
            mock_mcp.get_tools.return_value = [
                {"name": "mcp_notion_list", "description": "List", "parameters": {},
                 "_mcp_original_name": "list", "_mcp_server": "notion"},
            ]
            mock_mcp.call_tool = AsyncMock(return_value="notion result")

            registry = ToolRegistry(mcp_manager=mock_mcp)

            result = await registry.dispatch("mcp_notion_list", {"query": "test"}, {})
            self.assertEqual(result, "notion result")
            mock_mcp.call_tool.assert_called_once_with("mcp_notion_list", {"query": "test"})

        asyncio.run(_test())

    def test_dispatch_skill(self):
        from aureon_agent.tool_registry import ToolRegistry

        async def _test():
            mock_skills = MagicMock()
            mock_skills.get_tools.return_value = [
                {"name": "read_skill_caveman", "description": "Caveman", "parameters": {}},
            ]
            mock_skills.execute_tool = AsyncMock(return_value={"content": "caveman mode"})

            registry = ToolRegistry(skill_loader=mock_skills)

            result = await registry.dispatch("read_skill_caveman", {}, {})
            parsed = json.loads(result)
            self.assertEqual(parsed["content"], "caveman mode")

        asyncio.run(_test())

    def test_dispatch_unknown(self):
        from aureon_agent.tool_registry import ToolRegistry

        async def _test():
            registry = ToolRegistry()
            result = await registry.dispatch("nonexistent", {}, {})
            parsed = json.loads(result)
            self.assertIn("error", parsed)

        asyncio.run(_test())


class TestToolRegistryRefresh(unittest.TestCase):
    """Test cache invalidation."""

    def test_refresh_clears_cache(self):
        from aureon_agent.tool_registry import ToolRegistry

        mock_skills = MagicMock()
        mock_skills.get_tools.return_value = [
            {"name": "tool_a", "description": "A", "parameters": {}},
        ]

        registry = ToolRegistry(skill_loader=mock_skills)

        # First call populates cache
        tools1 = registry.get_all()
        self.assertEqual(len(tools1), 1)

        # Add a tool
        mock_skills.get_tools.return_value = [
            {"name": "tool_a", "description": "A", "parameters": {}},
            {"name": "tool_b", "description": "B", "parameters": {}},
        ]

        # Cached — still 1
        tools2 = registry.get_all()
        self.assertEqual(len(tools2), 1)

        # Refresh invalidates
        registry.refresh()
        tools3 = registry.get_all()
        self.assertEqual(len(tools3), 2)


class TestToolRegistryBackendQuery(unittest.TestCase):
    """Test get_backend()."""

    def test_backend_query(self):
        from aureon_agent.tool_registry import ToolRegistry

        mock_skills = MagicMock()
        mock_skills.get_tools.return_value = [
            {"name": "skill_tool", "description": "S", "parameters": {}},
        ]

        mock_mcp = MagicMock()
        mock_mcp.get_tools.return_value = [
            {"name": "mcp_notion_tool", "description": "M", "parameters": {},
             "_mcp_original_name": "tool", "_mcp_server": "notion"},
        ]

        registry = ToolRegistry(skill_loader=mock_skills, mcp_manager=mock_mcp)

        self.assertEqual(registry.get_backend("skill_tool"), "skill")
        self.assertEqual(registry.get_backend("mcp_notion_tool"), "mcp")
        self.assertEqual(registry.get_backend("nonexistent"), "unknown")


if __name__ == "__main__":
    unittest.main()
