"""Router confirmation flow is channel-agnostic (no telegram import)."""
import asyncio
import sys

from channels.router import ChannelRouter


class _PlainChannel:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


class _NativeChannel:
    def __init__(self):
        self.confirm = None

    async def send_message(self, chat_id, text):  # pragma: no cover - not used
        raise AssertionError("native confirmation should not use send_message")

    async def send_confirmation(self, chat_id, text, confirm_data, cancel_data):
        self.confirm = (chat_id, text, confirm_data, cancel_data)


def _router():
    return ChannelRouter(agent_runtime=None, session_manager=None, workspace_dir=".")


def test_plain_channel_gets_typed_reply_prompt():
    r = _router()
    ch = _PlainChannel()
    r.register("matrix", ch)
    asyncio.run(r.send_confirmation(
        "matrix:!room:example.org",
        "⚠️ **Confirmation Required**\ndelete it?\n\nTap ✅ Yes to proceed, or ❌ No to deny.",
        "confirm_yes", "confirm_no"))
    chat_id, text = ch.sent[0]
    assert chat_id == "!room:example.org"
    assert "delete it?" in text
    assert "Tap" not in text
    assert "yes" in text.lower() and "no" in text.lower()


def test_native_channel_receives_callback_data():
    r = _router()
    ch = _NativeChannel()
    r.register("telegram", ch)
    asyncio.run(r.send_confirmation("telegram:42", "sure?", "confirm_yes", "confirm_no"))
    assert ch.confirm == ("42", "sure?", "confirm_yes", "confirm_no")


def test_unknown_channel_is_noop():
    r = _router()
    asyncio.run(r.send_confirmation("matrix:!x:y", "hi", "a", "b"))  # must not raise


def test_router_module_does_not_import_telegram():
    import channels.router as mod
    src = open(mod.__file__).read()
    assert "from telegram" not in src and "import telegram" not in src
    assert "channels.router" in sys.modules
