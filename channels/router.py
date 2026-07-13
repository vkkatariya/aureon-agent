"""Multiplexes channels into the agent runtime: owns session bookkeeping so
adapters only deal with platform I/O (allowlisting, streaming throttle, chunking)."""
import asyncio
import logging

from lessons import append_lesson

logger = logging.getLogger(__name__)


class ChannelRouter:
    def __init__(self, agent_runtime, session_manager, workspace_dir):
        self.agent = agent_runtime
        self.sessions = session_manager
        self.workspace_dir = workspace_dir
        self.channels = {}

    def register(self, name, channel):
        self.channels[name] = channel

    async def start_all(self):
        await asyncio.gather(*(c.start() for c in self.channels.values()))

    async def stop_all(self):
        await asyncio.gather(*(c.stop() for c in self.channels.values()), return_exceptions=True)

    async def handle_message(self, channel_name, client_id, text, callbacks):
        session_id = await self.sessions.get_or_create_session(client_id, channel_name)
        await self.sessions.add_message(session_id, "user", text)

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
