import os
import tempfile

from aureon_agent.config import AureonConfig

def test_config_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, ".env")
        config = AureonConfig(
            TELEGRAM_BOT_TOKEN="123456789:ABCDEF",
            TELEGRAM_ALLOWED_CHATS="123,456",
            LOG_LEVEL="DEBUG"
        )
        config.save(path)
        
        # Check permissions
        stat = os.stat(path)
        assert oct(stat.st_mode)[-3:] == "600"
        
        loaded = AureonConfig.from_file(path)
        assert loaded.TELEGRAM_BOT_TOKEN == "123456789:ABCDEF"
        assert loaded.TELEGRAM_ALLOWED_CHATS == "123,456"
        assert loaded.LOG_LEVEL == "DEBUG"
        assert loaded.OLLAMA_BASE_URL == "http://127.0.0.1:11434/v1" # Default

def test_config_validation():
    # Empty channels
    c1 = AureonConfig()
    assert not c1.is_complete()
    
    # Needs API key for cloud
    c2 = AureonConfig(OLLAMA_BASE_URL="https://ollama.com/v1", TELEGRAM_BOT_TOKEN="token", TELEGRAM_ALLOWED_CHATS="123")
    errors = c2.validate()
    assert len(errors) == 1
    assert "OLLAMA_API_KEY" in errors[0]
    
    # Valid
    c3 = AureonConfig(TELEGRAM_BOT_TOKEN="token", TELEGRAM_ALLOWED_CHATS="123")
    assert c3.is_complete()
    assert len(c3.validate()) == 0
    
    # Missing allowed chats warning
    c4 = AureonConfig(TELEGRAM_BOT_TOKEN="token")
    assert "TELEGRAM_ALLOWED_CHATS" in c4.validate()[0]

def test_config_redaction():
    c = AureonConfig(
        TELEGRAM_BOT_TOKEN="1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        OLLAMA_API_KEY="short",
        OPENROUTER_API_KEY="sk-or-v1-abcdef1234567890",
        DISCORD_BOT_TOKEN="12345"
    )
    redacted = c.redact()
    assert redacted.TELEGRAM_BOT_TOKEN == "1234...WXYZ"
    assert redacted.OLLAMA_API_KEY == "***"
    assert redacted.OPENROUTER_API_KEY == "sk-o...7890"
    assert redacted.DISCORD_BOT_TOKEN == "***"

def test_config_openrouter():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, ".env")
        with open(path, "w") as f:
            f.write(
                "OPENROUTER_BASE_URL=https://openrouter.ai/api/v1\n"
                "OPENROUTER_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free\n"
                "OPENROUTER_API_KEY=test-key-123\n"
                "TELEGRAM_BOT_TOKEN=token\n"
                "TELEGRAM_ALLOWED_CHATS=123\n"
            )
        loaded = AureonConfig.from_file(path)
        assert loaded.base_url == "https://openrouter.ai/api/v1"
        assert loaded.model == "nvidia/nemotron-3-ultra-550b-a55b:free"
        assert loaded.api_key == "test-key-123"
        assert loaded.OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1"
        assert loaded.OLLAMA_BASE_URL == "https://openrouter.ai/api/v1"
        assert loaded.is_complete()
        assert len(loaded.validate()) == 0
