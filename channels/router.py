"""Multiplexes channels into the agent runtime: owns session bookkeeping so
adapters only deal with platform I/O (allowlisting, streaming throttle, chunking)."""
import asyncio
import logging

from lessons import append_lesson

logger = logging.getLogger(__name__)

# Button-oriented instruction appended by confirm_with_captain; stripped for
# channels without inline buttons (exact match, never a substring line filter).
BUTTON_HINT = "Tap ✅ Yes to proceed, or ❌ No to deny."


def plain_confirmation_text(text, extra=""):
    """Swap the button-oriented instruction for a typed-reply one (exact-match
    strip, never a substring line filter). `extra` appends a channel-specific
    hint, e.g. Matrix's reaction option."""
    body = text.replace(BUTTON_HINT, "").rstrip()
    return f"{body}\n\nReply **yes** to proceed or **no** to deny.{extra}"


class ChannelRouter:
    def __init__(self, agent_runtime, session_manager, workspace_dir):
        self.agent = agent_runtime
        self.sessions = session_manager
        self.workspace_dir = workspace_dir
        self.channels = {}
        self.pending_confirmations = {}  # session_id -> asyncio.Future
        self.pending_clarifications = {} # session_id -> asyncio.Future
        self.session_clarify_counts = {} # session_id -> int

    def register(self, name, channel):
        self.channels[name] = channel

    async def start_all(self):
        await asyncio.gather(*(c.start() for c in self.channels.values()))

    async def stop_all(self):
        await asyncio.gather(*(c.stop() for c in self.channels.values()), return_exceptions=True)

    async def send_message(self, session_id, text):
        if ":" not in session_id:
            logger.error("Invalid session_id format: %s", session_id)
            return
        channel_name, client_id = session_id.split(":", 1)
        if channel_name in self.channels:
            await self.channels[channel_name].send_message(client_id, text)
        else:
            logger.error("Channel %s not found for send_message", channel_name)

    async def send_confirmation(self, session_id, text, confirm_data, cancel_data):
        """Send a confirmation prompt.

        Channels with native confirm UI (Telegram inline keyboard) expose a
        `send_confirmation` method and handle it themselves. All others get a
        plain-text prompt; a typed "yes"/"no" reply resolves the pending future
        via handle_message (Matrix additionally accepts ✅/❌ reactions).
        """
        if ":" not in session_id:
            logger.error("Invalid session_id format: %s", session_id)
            return
        channel_name, client_id = session_id.split(":", 1)
        channel = self.channels.get(channel_name)
        if channel is None:
            logger.error("Channel %s not found for send_confirmation", channel_name)
            return
        native = getattr(channel, "send_confirmation", None)
        if native is not None:
            await native(client_id, text, confirm_data, cancel_data)
            return
        await channel.send_message(client_id, self._plain_confirmation_text(text))

    @staticmethod
    def _plain_confirmation_text(text):
        return plain_confirmation_text(text)

    async def handle_message(self, channel_name, client_id, text, callbacks):
        session_id = await self.sessions.get_or_create_session(client_id, channel_name)
        
        # Check if there is a pending confirmation for this session
        if session_id in self.pending_confirmations:
            future = self.pending_confirmations[session_id]
            if not future.done():
                future.set_result(text)
                return None # Consumed by confirmation
                
        # Check if there is a pending clarification for this session
        if session_id in self.pending_clarifications:
            future = self.pending_clarifications[session_id]
            if not future.done():
                future.set_result(text)
                return None # Consumed by clarification

        await self.sessions.add_message(session_id, "user", text)
        
        # We also need to inject channel info into the context for tools
        if "context" not in callbacks:
            callbacks["context"] = {}
        callbacks["context"]["router"] = self
        callbacks["context"]["session_id"] = session_id
        callbacks["context"]["channel_name"] = channel_name
        callbacks["context"]["client_id"] = client_id

        if text.strip().startswith("/lesson"):
            response = await self._handle_lesson_command(text)
        else:
            history = await self.sessions.get_history(session_id)
            try:
                response = await self.agent.run(history, session_id, callbacks)
            except Exception as e:
                logger.error("agent run failed for %s: %s", session_id, e)
                raise

        if response:
            await self.sessions.add_message(session_id, "assistant", response)
        return response

    async def _handle_lesson_command(self, text):
        note = text.strip()[len("/lesson"):].strip()
        if not note:
            return "Usage: /lesson <what to remember>"
        await append_lesson(
            self.workspace_dir,
            context=note,
            what_went_wrong="(reported via /lesson)",
            root_cause="(not specified)",
            prevention_rule=note,
        )
        return "Logged to lessons.md."
