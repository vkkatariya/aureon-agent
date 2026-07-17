import os
from dataclasses import dataclass
from typing import List, Optional
from dotenv import dotenv_values, set_key

@dataclass
class AureonConfig:
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434/v1"
    OLLAMA_API_KEY: Optional[str] = None
    OLLAMA_MODEL: str = "minimax-m2.5:cloud"
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_ALLOWED_CHATS: str = ""
    DISCORD_BOT_TOKEN: Optional[str] = None
    HEALTH_PORT: str = "7777"
    LOG_LEVEL: str = "INFO"

    @classmethod
    def from_env(cls) -> "AureonConfig":
        return cls(
            OLLAMA_BASE_URL=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
            OLLAMA_API_KEY=os.getenv("OLLAMA_API_KEY"),
            OLLAMA_MODEL=os.getenv("OLLAMA_MODEL", "minimax-m2.5:cloud"),
            TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN"),
            TELEGRAM_ALLOWED_CHATS=os.getenv("TELEGRAM_ALLOWED_CHATS", ""),
            DISCORD_BOT_TOKEN=os.getenv("DISCORD_BOT_TOKEN"),
            HEALTH_PORT=os.getenv("HEALTH_PORT", "7777"),
            LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO"),
        )

    @classmethod
    def from_file(cls, path: str) -> "AureonConfig":
        if not os.path.exists(path):
            return cls()
        values = dotenv_values(path)
        return cls(
            OLLAMA_BASE_URL=values.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1"),
            OLLAMA_API_KEY=values.get("OLLAMA_API_KEY"),
            OLLAMA_MODEL=values.get("OLLAMA_MODEL", "minimax-m2.5:cloud"),
            TELEGRAM_BOT_TOKEN=values.get("TELEGRAM_BOT_TOKEN"),
            TELEGRAM_ALLOWED_CHATS=values.get("TELEGRAM_ALLOWED_CHATS", ""),
            DISCORD_BOT_TOKEN=values.get("DISCORD_BOT_TOKEN"),
            HEALTH_PORT=values.get("HEALTH_PORT", "7777"),
            LOG_LEVEL=values.get("LOG_LEVEL", "INFO"),
        )

    def save(self, path: str):
        # Create empty if not exists to chmod
        if not os.path.exists(path):
            with open(path, "w") as f:
                f.write("")
        os.chmod(path, 0o600)
        for key, value in self.__dict__.items():
            if value is not None:
                set_key(path, key, str(value))
            else:
                # Remove key if none
                pass

    def validate(self) -> List[str]:
        errors = []
        if self.OLLAMA_BASE_URL == "https://ollama.com/v1" and not self.OLLAMA_API_KEY:
            errors.append("OLLAMA_API_KEY is required for ollama.com base URL")
        if self.TELEGRAM_BOT_TOKEN and not self.TELEGRAM_ALLOWED_CHATS:
            errors.append("TELEGRAM_ALLOWED_CHATS is empty — all Telegram messages will be dropped")
        if self.HEALTH_PORT:
            if not str(self.HEALTH_PORT).isdigit():
                errors.append("HEALTH_PORT must be an integer")
        return errors

    def redact(self) -> "AureonConfig":
        def redact_token(t: str | None) -> str | None:
            if not t:
                return t
            return f"{t[:4]}...{t[-4:]}" if len(t) > 8 else "***"

        return AureonConfig(
            OLLAMA_BASE_URL=self.OLLAMA_BASE_URL,
            OLLAMA_API_KEY=redact_token(self.OLLAMA_API_KEY),
            OLLAMA_MODEL=self.OLLAMA_MODEL,
            TELEGRAM_BOT_TOKEN=redact_token(self.TELEGRAM_BOT_TOKEN),
            TELEGRAM_ALLOWED_CHATS=self.TELEGRAM_ALLOWED_CHATS,
            DISCORD_BOT_TOKEN=redact_token(self.DISCORD_BOT_TOKEN),
            HEALTH_PORT=self.HEALTH_PORT,
            LOG_LEVEL=self.LOG_LEVEL,
        )

    def is_complete(self) -> bool:
        # It's complete if we have at least one channel configured, and no validation errors
        if not self.TELEGRAM_BOT_TOKEN and not self.DISCORD_BOT_TOKEN:
            return False
        return len(self.validate()) == 0

def get_chat_id_from_update(token: str) -> Optional[str]:
    import httpx
    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        res = httpx.get(url, timeout=5).json()
        if res.get("ok") and res.get("result"):
            for update in reversed(res["result"]):
                if "message" in update and "chat" in update["message"]:
                    return str(update["message"]["chat"]["id"])
    except Exception:
        pass
    return None
