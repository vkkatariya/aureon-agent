"""Tests for MCP client module.

Tests cover:
  - MCPClient schema translation
  - MCPClient tool prefixing
  - MCPManager multi-server management
  - Error handling (server not found, server disconnect)
  - Tool listing and routing

Note: These tests mock the MCP SDK — no real MCP server needed.
"""
import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMCPSchemaTranslation(unittest.TestCase):
    """Test MCP inputSchema → OpenAI parameters translation."""

    def test_translate_basic_schema(self):
        from aureon_agent.mcp_client import MCPClient

        schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        }
        result = MCPClient._translate_schema(schema)
        self.assertEqual(result["type"], "object")
        self.assertIn("query", result["properties"])
        self.assertEqual(result["required"], ["query"])

    def test_translate_empty_schema(self):
        from aureon_agent.mcp_client import MCPClient

        result = MCPClient._translate_schema({})
        self.assertEqual(result["type"], "object")
        self.assertEqual(result["properties"], {})

    def test_translate_none_schema(self):
        from aureon_agent.mcp_client import MCPClient

        result = MCPClient._translate_schema(None)
        self.assertEqual(result["type"], "object")
        self.assertEqual(result["properties"], {})

    def test_translate_schema_missing_type(self):
        from aureon_agent.mcp_client import MCPClient

        schema = {"properties": {"x": {"type": "string"}}}
        result = MCPClient._translate_schema(schema)
        self.assertEqual(result["type"], "object")


class TestMCPClientToolPrefixing(unittest.TestCase):
    """Test that MCP tools get prefixed correctly."""

    def test_tool_prefixing(self):
        from aureon_agent.mcp_client import MCPClient

        client = MCPClient("notion", command="mcp-server-notion")

        # Simulate tool discovery
        mock_tool = MagicMock()
        mock_tool.name = "list_pages"
        mock_tool.description = "List all pages"
        mock_tool.inputSchema = {"type": "object", "properties": {}}

        # Manually build what _discover_tools would produce
        prefixed_name = f"{client.prefix}_{client.server_name}_{mock_tool.name}"
        self.assertEqual(prefixed_name, "mcp_notion_list_pages")

    def test_has_tool(self):
        from aureon_agent.mcp_client import MCPClient

        client = MCPClient("notion", command="mcp-server-notion")
        client._tools = [{"name": "mcp_notion_list_pages", "_mcp_original_name": "list_pages", "_mcp_server": "notion"}]
        client._tool_names = {"mcp_notion_list_pages"}

        self.assertTrue(client.has_tool("mcp_notion_list_pages"))
        self.assertFalse(client.has_tool("mcp_notion_nonexistent"))
        self.assertFalse(client.has_tool("list_pages"))  # unprefixed


class TestMCPClientCallTool(unittest.TestCase):
    """Test tool calling with mocked MCP session."""

    def test_call_tool_not_connected(self):
        from aureon_agent.mcp_client import MCPClient

        async def _test():
            client = MCPClient("notion", command="mcp-server-notion")
            result = await client.call_tool("mcp_notion_list_pages", {})
            data = json.loads(result)
            self.assertIn("error", data)
            self.assertIn("not connected", data["error"])

        asyncio.run(_test())

    def test_call_tool_not_found(self):
        from aureon_agent.mcp_client import MCPClient

        async def _test():
            client = MCPClient("notion", command="mcp-server-notion")
            client._connected = True
            client._session = MagicMock()
            client._tools = []
            client._tool_names = set()

            result = await client.call_tool("mcp_notion_nonexistent", {})
            data = json.loads(result)
            self.assertIn("error", data)
            self.assertIn("not found", data["error"])

        asyncio.run(_test())

    def test_call_tool_success(self):
        from aureon_agent.mcp_client import MCPClient

        async def _test():
            client = MCPClient("notion", command="mcp-server-notion")
            client._connected = True

            # Mock session.call_tool
            mock_content = MagicMock()
            mock_content.text = "Page 1: Test Page"
            mock_result = MagicMock()
            mock_result.content = [mock_content]
            mock_result.isError = False

            client._session = MagicMock()
            client._session.call_tool = AsyncMock(return_value=mock_result)

            client._tools = [{
                "name": "mcp_notion_list_pages",
                "description": "List pages",
                "parameters": {},
                "_mcp_original_name": "list_pages",
                "_mcp_server": "notion",
            }]
            client._tool_names = {"mcp_notion_list_pages"}

            result = await client.call_tool("mcp_notion_list_pages", {})
            self.assertEqual(result, "Page 1: Test Page")
            client._session.call_tool.assert_called_once_with("list_pages", {})

        asyncio.run(_test())

    def test_call_tool_server_error(self):
        from aureon_agent.mcp_client import MCPClient

        async def _test():
            client = MCPClient("notion", command="mcp-server-notion")
            client._connected = True

            # Mock session.call_tool that raises
            client._session = MagicMock()
            client._session.call_tool = AsyncMock(side_effect=ConnectionError("broken pipe"))

            client._tools = [{
                "name": "mcp_notion_list_pages",
                "_mcp_original_name": "list_pages",
                "_mcp_server": "notion",
            }]
            client._tool_names = {"mcp_notion_list_pages"}

            result = await client.call_tool("mcp_notion_list_pages", {})
            data = json.loads(result)
            self.assertIn("error", data)
            self.assertIn("unreachable", data["error"])
            # Client should mark itself as disconnected
            self.assertFalse(client._connected)

        asyncio.run(_test())


class TestMCPManager(unittest.TestCase):
    """Test multi-server management."""

    def test_empty_manager(self):
        from aureon_agent.mcp_client import MCPManager

        manager = MCPManager()
        self.assertEqual(manager.tool_count, 0)
        self.assertEqual(manager.get_tools(), [])
        self.assertFalse(manager.has_tool("anything"))

    def test_tool_routing(self):
        from aureon_agent.mcp_client import MCPManager

        async def _test():
            manager = MCPManager()

            # Manually add a mock client
            mock_client = MagicMock()
            mock_client.tools = [
                {"name": "mcp_notion_list_pages", "_mcp_original_name": "list_pages", "_mcp_server": "notion"},
            ]
            mock_client.call_tool = AsyncMock(return_value="success")

            manager.clients["notion"] = mock_client
            manager._rebuild_tool_index()

            self.assertTrue(manager.has_tool("mcp_notion_list_pages"))
            self.assertFalse(manager.has_tool("mcp_github_list_repos"))

            result = await manager.call_tool("mcp_notion_list_pages", {"arg": "val"})
            self.assertEqual(result, "success")
            mock_client.call_tool.assert_called_once_with("mcp_notion_list_pages", {"arg": "val"})

        asyncio.run(_test())

    def test_call_unknown_tool(self):
        from aureon_agent.mcp_client import MCPManager

        async def _test():
            manager = MCPManager()
            result = await manager.call_tool("mcp_unknown_tool", {})
            data = json.loads(result)
            self.assertIn("error", data)

        asyncio.run(_test())


class TestMCPConfigError(unittest.TestCase):
    """Test MCPConfigError on missing binary."""

    def test_file_not_found_raises_config_error(self):
        from aureon_agent.mcp_client import MCPClient, MCPConfigError

        async def _test():
            client = MCPClient("bad", command="nonexistent-binary-xyz-123")
            with self.assertRaises(MCPConfigError) as ctx:
                await client.connect()
            self.assertIn("not found", str(ctx.exception))

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
