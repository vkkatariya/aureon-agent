"""Tests for Gmail MCP client config.

Tests cover:
  - Gmail MCP configuration block parsing
  - Gmail token fallback logic
"""
import asyncio
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aureon_agent.mcp_client import MCPClient, MCPManager

class TestGmailCliConfig(unittest.TestCase):
    """Test the Gmail configuration block in _parse_mcp_servers."""

    @patch("os.getenv")
    @patch("os.path.exists")
    def test_gmail_credentials(self, mock_exists, mock_getenv):
        from aureon_agent.cli import _parse_mcp_servers

        def getenv_side_effect(key, default=None):
            if key == "GMAIL_API_CLIENT_ID":
                return "test-client-id"
            if key == "GMAIL_API_CLIENT_SECRET":
                return "test-client-secret"
            return None
            
        def exists_side_effect(path):
            if "notion" in str(path) or "github" in str(path):
                return False
            if "multi-email-mcp" in str(path):
                return True
            if "vishal.json" in str(path):
                return True
            if ".oauth" in str(path):
                return False
            return False

        mock_getenv.side_effect = getenv_side_effect
        mock_exists.side_effect = exists_side_effect

        servers = _parse_mcp_servers()
        gmail_cfg = next((s for s in servers if s["server_name"] == "gmail"), None)
        
        self.assertIsNotNone(gmail_cfg)
        self.assertEqual(gmail_cfg["command"], "node")
        self.assertTrue(gmail_cfg["args"][0].endswith("server.js"))
        self.assertEqual(gmail_cfg["env"]["MAIL_ACCOUNTS"], "vishal")
        self.assertEqual(gmail_cfg["env"]["MAIL_vishal_GMAIL_API_CLIENT_ID"], "test-client-id")
        self.assertEqual(gmail_cfg["env"]["MAIL_vishal_GMAIL_API_CLIENT_SECRET"], "test-client-secret")

    @patch("os.getenv")
    @patch("os.path.exists")
    def test_gmail_missing_binary(self, mock_exists, mock_getenv):
        from aureon_agent.cli import _parse_mcp_servers

        def getenv_side_effect(key, default=None):
            if key == "GMAIL_API_CLIENT_ID":
                return "test-client-id"
            if key == "GMAIL_API_CLIENT_SECRET":
                return "test-client-secret"
            return None
            
        def exists_side_effect(path):
            return False

        mock_getenv.side_effect = getenv_side_effect
        mock_exists.side_effect = exists_side_effect

        servers = _parse_mcp_servers()
        gmail_cfg = next((s for s in servers if s["server_name"] == "gmail"), None)
        
        self.assertIsNone(gmail_cfg)


if __name__ == "__main__":
    unittest.main()
