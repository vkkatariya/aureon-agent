import os
from dataclasses import dataclass
from typing import List, Optional
from dotenv import dotenv_values, set_key

_DEFAULT_MATRIX_HOMESERVER = "https://matrix.auxois-wyrm.ts.net"


def _parse_bool(value, default: bool) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class AureonConfig:
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434/v1"
    OLLAMA_API_KEY: Optional[str] = None
    OLLAMA_MODEL: str = "minimax-m2.5:cloud"
    OPENROUTER_BASE_URL: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_MODEL: Optional[str] = None
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_ALLOWED_CHATS: str = ""
    DISCORD_BOT_TOKEN: Optional[str] = None
    MATRIX_HOMESERVER: str = "https://matrix.auxois-wyrm.ts.net"
    MATRIX_USER_ID: Optional[str] = None
    MATRIX_ACCESS_TOKEN: Optional[str] = None
    MATRIX_DEVICE_ID: str = "AUREON_ARM64"
    MATRIX_ALLOWED_USERS: str = ""
    MATRIX_HOME_ROOM: Optional[str] = None
    MATRIX_ENCRYPTION: bool = True
    HEALTH_PORT: str = "7777"
    LOG_LEVEL: str = "INFO"

    @property
    def base_url(self) -> str:
        return self.OPENROUTER_BASE_URL or self.OLLAMA_BASE_URL

    @property
    def api_key(self) -> Optional[str]:
        return self.OPENROUTER_API_KEY or self.OLLAMA_API_KEY

    @property
    def model(self) -> str:
        return self.OPENROUTER_MODEL or self.OLLAMA_MODEL

    @property
    def matrix_configured(self) -> bool:
        return bool(self.MATRIX_HOMESERVER and self.MATRIX_USER_ID and self.MATRIX_ACCESS_TOKEN)

    @property
    def matrix_allowed_users(self) -> set:
        return {u.strip() for u in (self.MATRIX_ALLOWED_USERS or "").split(",") if u.strip()}

    @classmethod
    def from_env(cls) -> "AureonConfig":
        openrouter_url = os.getenv("OPENROUTER_BASE_URL")
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        openrouter_model = os.getenv("OPENROUTER_MODEL")
        ollama_url = openrouter_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
        ollama_key = openrouter_key or os.getenv("OLLAMA_API_KEY")
        ollama_model = openrouter_model or os.getenv("OLLAMA_MODEL", "minimax-m2.5:cloud")
        return cls(
            OLLAMA_BASE_URL=ollama_url,
            OLLAMA_API_KEY=ollama_key,
            OLLAMA_MODEL=ollama_model,
            OPENROUTER_BASE_URL=openrouter_url,
            OPENROUTER_API_KEY=openrouter_key,
            OPENROUTER_MODEL=openrouter_model,
            TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN"),
            TELEGRAM_ALLOWED_CHATS=os.getenv("TELEGRAM_ALLOWED_CHATS", ""),
            DISCORD_BOT_TOKEN=os.getenv("DISCORD_BOT_TOKEN"),
            MATRIX_HOMESERVER=os.getenv("MATRIX_HOMESERVER") or _DEFAULT_MATRIX_HOMESERVER,
            MATRIX_USER_ID=os.getenv("MATRIX_USER_ID"),
            MATRIX_ACCESS_TOKEN=os.getenv("MATRIX_ACCESS_TOKEN"),
            MATRIX_DEVICE_ID=os.getenv("MATRIX_DEVICE_ID") or "AUREON_ARM64",
            MATRIX_ALLOWED_USERS=os.getenv("MATRIX_ALLOWED_USERS", ""),
            MATRIX_HOME_ROOM=os.getenv("MATRIX_HOME_ROOM"),
            MATRIX_ENCRYPTION=_parse_bool(os.getenv("MATRIX_ENCRYPTION"), True),
            HEALTH_PORT=os.getenv("HEALTH_PORT", "7777"),
            LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO"),
        )

    @classmethod
    def from_file(cls, path: str) -> "AureonConfig":
        if not os.path.exists(path):
            return cls()
        values = dotenv_values(path)
        openrouter_url = values.get("OPENROUTER_BASE_URL")
        openrouter_key = values.get("OPENROUTER_API_KEY")
        openrouter_model = values.get("OPENROUTER_MODEL")
        ollama_url = openrouter_url or values.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1"
        ollama_key = openrouter_key or values.get("OLLAMA_API_KEY")
        ollama_model = openrouter_model or values.get("OLLAMA_MODEL") or "minimax-m2.5:cloud"
        return cls(
            OLLAMA_BASE_URL=ollama_url,
            OLLAMA_API_KEY=ollama_key,
            OLLAMA_MODEL=ollama_model,
            OPENROUTER_BASE_URL=openrouter_url,
            OPENROUTER_API_KEY=openrouter_key,
            OPENROUTER_MODEL=openrouter_model,
            TELEGRAM_BOT_TOKEN=values.get("TELEGRAM_BOT_TOKEN"),
            TELEGRAM_ALLOWED_CHATS=values.get("TELEGRAM_ALLOWED_CHATS", ""),
            DISCORD_BOT_TOKEN=values.get("DISCORD_BOT_TOKEN"),
            MATRIX_HOMESERVER=values.get("MATRIX_HOMESERVER") or _DEFAULT_MATRIX_HOMESERVER,
            MATRIX_USER_ID=values.get("MATRIX_USER_ID"),
            MATRIX_ACCESS_TOKEN=values.get("MATRIX_ACCESS_TOKEN"),
            MATRIX_DEVICE_ID=values.get("MATRIX_DEVICE_ID") or "AUREON_ARM64",
            MATRIX_ALLOWED_USERS=values.get("MATRIX_ALLOWED_USERS") or "",
            MATRIX_HOME_ROOM=values.get("MATRIX_HOME_ROOM"),
            MATRIX_ENCRYPTION=_parse_bool(values.get("MATRIX_ENCRYPTION"), True),
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
        if self.OPENROUTER_BASE_URL and not (self.OPENROUTER_API_KEY or self.OLLAMA_API_KEY):
            errors.append("OPENROUTER_API_KEY is required for OpenRouter base URL")
        if self.TELEGRAM_BOT_TOKEN and not self.TELEGRAM_ALLOWED_CHATS:
            errors.append("TELEGRAM_ALLOWED_CHATS is empty — all Telegram messages will be dropped")
        if (self.MATRIX_USER_ID or self.MATRIX_ACCESS_TOKEN) and not self.matrix_allowed_users:
            errors.append("MATRIX_ALLOWED_USERS is empty — all Matrix messages will be dropped")
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
            OPENROUTER_BASE_URL=self.OPENROUTER_BASE_URL,
            OPENROUTER_API_KEY=redact_token(self.OPENROUTER_API_KEY),
            OPENROUTER_MODEL=self.OPENROUTER_MODEL,
            TELEGRAM_BOT_TOKEN=redact_token(self.TELEGRAM_BOT_TOKEN),
            TELEGRAM_ALLOWED_CHATS=self.TELEGRAM_ALLOWED_CHATS,
            DISCORD_BOT_TOKEN=redact_token(self.DISCORD_BOT_TOKEN),
            MATRIX_HOMESERVER=self.MATRIX_HOMESERVER,
            MATRIX_USER_ID=self.MATRIX_USER_ID,
            MATRIX_ACCESS_TOKEN=redact_token(self.MATRIX_ACCESS_TOKEN),
            MATRIX_DEVICE_ID=self.MATRIX_DEVICE_ID,
            MATRIX_ALLOWED_USERS=self.MATRIX_ALLOWED_USERS,
            MATRIX_HOME_ROOM=self.MATRIX_HOME_ROOM,
            MATRIX_ENCRYPTION=self.MATRIX_ENCRYPTION,
            HEALTH_PORT=self.HEALTH_PORT,
            LOG_LEVEL=self.LOG_LEVEL,
        )

    def is_complete(self) -> bool:
        # It's complete if we have at least one channel configured, and no validation errors
        if not (self.matrix_configured or self.TELEGRAM_BOT_TOKEN or self.DISCORD_BOT_TOKEN):
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
