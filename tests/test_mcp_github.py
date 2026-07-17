"""Tests for GitHub MCP client.

Tests cover:
  - GitHub MCP schema translation
  - GitHub tool execution (mocked)
  - GitHub token parsing logic in cli.py
  - GitHub missing binary logic
"""
import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aureon_agent.mcp_client import MCPClient, MCPManager, MCPConfigError


class TestGitHubMCPClient(unittest.TestCase):
    """Test GitHub MCP specifics."""

    def test_github_tool_prefixing(self):
        client = MCPClient("github", command="node", args=["dummy.js"])
        
        mock_tool = MagicMock()
        mock_tool.name = "list_prs"
        mock_tool.description = "List pull requests"
        mock_tool.inputSchema = {"type": "object", "properties": {}}

        prefixed_name = f"{client.prefix}_{client.server_name}_{mock_tool.name}"
        self.assertEqual(prefixed_name, "mcp_github_list_prs")

    def test_github_call_tool_success(self):
        async def _test():
            client = MCPClient("github", command="node", args=["dummy.js"])
            client._connected = True

            # Mock session.call_tool
            mock_content = MagicMock()
            mock_content.text = "PR #1: Add GitHub MCP"
            mock_result = MagicMock()
            mock_result.content = [mock_content]
            mock_result.isError = False

            client._session = MagicMock()
            client._session.call_tool = AsyncMock(return_value=mock_result)

            client._tools = [{
                "name": "mcp_github_list_prs",
                "description": "List PRs",
                "parameters": {},
                "_mcp_original_name": "list_prs",
                "_mcp_server": "github",
            }]
            client._tool_names = {"mcp_github_list_prs"}

            result = await client.call_tool("mcp_github_list_prs", {})
            self.assertEqual(result, "PR #1: Add GitHub MCP")
            client._session.call_tool.assert_called_once_with("list_prs", {})

        asyncio.run(_test())

    def test_github_call_tool_error(self):
        async def _test():
            client = MCPClient("github", command="node", args=["dummy.js"])
            client._connected = True

            # Mock session.call_tool to return an error response
            mock_content = MagicMock()
            mock_content.text = "API rate limit exceeded"
            mock_result = MagicMock()
            mock_result.content = [mock_content]
            mock_result.isError = True

            client._session = MagicMock()
            client._session.call_tool = AsyncMock(return_value=mock_result)

            client._tools = [{
                "name": "mcp_github_list_prs",
                "_mcp_original_name": "list_prs",
                "_mcp_server": "github",
            }]
            client._tool_names = {"mcp_github_list_prs"}

            result = await client.call_tool("mcp_github_list_prs", {})
            data = json.loads(result)
            self.assertIn("error", data)
            self.assertIn("API rate limit exceeded", data["error"])

        asyncio.run(_test())


class TestGitHubCliConfig(unittest.TestCase):
    """Test the GitHub configuration block in _parse_mcp_servers."""

    @patch("os.getenv")
    @patch("os.path.exists")
    def test_github_token_hermes_style(self, mock_exists, mock_getenv):
        from aureon_agent.cli import _parse_mcp_servers

        def getenv_side_effect(key, default=None):
            if key == "GITHUB_TOKEN":
                return "ghp_12345"
            return None
            
        mock_getenv.side_effect = getenv_side_effect
        mock_exists.side_effect = lambda path: str(path).endswith(
            "@modelcontextprotocol/server-github/dist/index.js"
        )

        servers = _parse_mcp_servers()
        github_cfg = next((s for s in servers if s["server_name"] == "github"), None)
        
        self.assertIsNotNone(github_cfg)
        self.assertEqual(github_cfg["command"], "node")
        self.assertTrue(github_cfg["args"][0].endswith("index.js"))
        self.assertEqual(github_cfg["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"], "ghp_12345")

    @patch("os.getenv")
    @patch("os.path.exists")
    def test_github_binary_missing(self, mock_exists, mock_getenv):
        from aureon_agent.cli import _parse_mcp_servers

        def getenv_side_effect(key, default=None):
            if key == "GITHUB_TOKEN":
                return "ghp_12345"
            return None
            
        mock_getenv.side_effect = getenv_side_effect
        # Binary not found
        mock_exists.return_value = False

        servers = _parse_mcp_servers()
        github_cfg = next((s for s in servers if s["server_name"] == "github"), None)
        
        # If binary is missing, _parse_mcp_servers should skip adding the server
        self.assertIsNone(github_cfg)


if __name__ == "__main__":
    unittest.main()
