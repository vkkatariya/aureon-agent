import pytest
from unittest.mock import patch, MagicMock
from aureon_agent.setup import run_setup
from aureon_agent.config import AureonConfig
import argparse

@patch("aureon_agent.setup.print_banner")
@patch("aureon_agent.setup.step_existing_config")
@patch("aureon_agent.setup.step_model")
@patch("aureon_agent.setup.step_telegram")
@patch("aureon_agent.setup.step_discord")
@patch("aureon_agent.setup.step_daemon_skills")
def test_setup_non_interactive(mock_daemon, mock_discord, mock_telegram, mock_model, mock_existing, mock_banner):
    mock_existing.return_value = AureonConfig()
    
    args = argparse.Namespace(
        quick=False,
        non_interactive=True,
        reset=False,
        section="all",
        telegram_bot_token="test_token",
        telegram_allowed_chats="123",
        discord_bot_token=None,
        ollama_base_url=None,
        ollama_api_key=None,
        ollama_model=None
    )
    
    with patch.object(AureonConfig, "save") as mock_save:
        run_setup(args)
        mock_save.assert_called_once()
        
    mock_model.assert_called_once()
    mock_telegram.assert_called_once()
    mock_discord.assert_called_once()
    mock_daemon.assert_called_once()
