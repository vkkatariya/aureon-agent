"""Channel ABC — one adapter per chat platform (Telegram, Discord, ...)."""
from abc import ABC, abstractmethod


class Channel(ABC):
    @abstractmethod
    async def start(self):
        """Begin listening for incoming messages."""

    @abstractmethod
    async def send_message(self, chat_id, text):
        """Send a new message, return a platform message handle."""

    @abstractmethod
    async def edit_message(self, chat_id, message_id, text):
        """Update a previously sent message (used for streaming)."""

    @abstractmethod
    async def send_action(self, chat_id, action):
        """Send a transient status indicator, e.g. 'typing'."""

    @abstractmethod
    async def stop(self):
        """Graceful shutdown."""
