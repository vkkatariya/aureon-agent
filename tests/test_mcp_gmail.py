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
            if key == "EMAIL_ADDRESS":
                return "test@gmail.com"
            if key == "EMAIL_PASSWORD":
                return "1234abcd5678efgh"
            return None
            
        mock_getenv.side_effect = getenv_side_effect
        mock_exists.return_value = True

        servers = _parse_mcp_servers()
        gmail_cfg = next((s for s in servers if s["server_name"] == "gmail"), None)
        
        self.assertIsNotNone(gmail_cfg)
        self.assertEqual(gmail_cfg["command"], "node")
        self.assertTrue(gmail_cfg["args"][0].endswith("index.js"))
        self.assertEqual(gmail_cfg["env"]["GMAIL_EMAIL"], "test@gmail.com")
        self.assertEqual(gmail_cfg["env"]["GMAIL_APP_PASSWORD"], "1234abcd5678efgh")

    @patch("os.getenv")
    @patch("os.path.exists")
    def test_gmail_missing_binary(self, mock_exists, mock_getenv):
        from aureon_agent.cli import _parse_mcp_servers

        def getenv_side_effect(key, default=None):
            if key == "EMAIL_ADDRESS":
                return "test@gmail.com"
            if key == "EMAIL_PASSWORD":
                return "1234"
            return None
            
        mock_getenv.side_effect = getenv_side_effect
        mock_exists.return_value = False

        servers = _parse_mcp_servers()
        gmail_cfg = next((s for s in servers if s["server_name"] == "gmail"), None)
        
        self.assertIsNone(gmail_cfg)


if __name__ == "__main__":
    unittest.main()
