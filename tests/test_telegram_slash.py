"""Tests for the Telegram /command code-block wrapping (channels/telegram.py).

The Rich tables from /sessions, /doctor, /status etc. collapse in Telegram
plain text; they must be delivered inside a MarkdownV2 fenced code block."""
import asyncio

from channels.telegram import (
    CODEBLOCK_CHUNK_LEN,
    NEW_CANCEL,
    NEW_CONFIRM,
    SLASH_COMMANDS,
    TelegramChannel,
    _chunk_for_codeblock,
    _md_code_block,
)


# --- lightweight fakes ---------------------------------------------------

class _FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})


class _FakeApp:
    def __init__(self):
        self.bot = _FakeBot()


class _Chat:
    def __init__(self, cid):
        self.id = cid


class _Msg:
    def __init__(self, text):
        self.text = text


class _Update:
    def __init__(self, cid, text):
        self.effective_chat = _Chat(cid)
        self.message = _Msg(text)


class _Query:
    def __init__(self, data):
        self.data = data
        self.answered = False
        self.edited = None

    async def answer(self):
        self.answered = True

    async def edit_message_text(self, text):
        self.edited = text


class _CbUpdate:
    def __init__(self, cid, data):
        self.effective_chat = _Chat(cid)
        self.callback_query = _Query(data)


class _FakeSessions:
    def __init__(self, cleared):
        self._cleared = cleared
        self.called_with = None

    async def clear_session(self, session_id):
        self.called_with = session_id
        return self._cleared


class _FakeRouter:
    def __init__(self, sessions):
        self.sessions = sessions


def _channel(sessions=None, allowed=("723865496",)):
    ch = TelegramChannel("token", _FakeRouter(sessions), set(allowed))
    ch._app = _FakeApp()
    return ch


def test_md_code_block_fences():
    wrapped = _md_code_block("Chat Sessions\n┏━━┓\n┃id┃\n┗━━┛")
    assert wrapped.startswith("```")
    assert wrapped.endswith("```")
    # box-drawing content preserved intact between the fences
    assert "┏━━┓" in wrapped


def test_md_code_block_escapes_backticks_and_backslashes():
    wrapped = _md_code_block("path C:\\tmp and `code`")
    body = wrapped[len("```\n"):-len("\n```")]
    assert "\\\\" in body       # backslash escaped
    assert "\\`" in body        # backtick escaped


def test_chunk_for_codeblock_splits_large_output():
    big = "x" * (CODEBLOCK_CHUNK_LEN * 2 + 10)
    chunks = _chunk_for_codeblock(big)
    assert len(chunks) == 3
    assert all(len(c) <= CODEBLOCK_CHUNK_LEN for c in chunks)


def test_chunk_for_codeblock_empty_yields_one():
    assert _chunk_for_codeblock("   ") == [""]


def test_every_chunk_independently_fenced():
    big = "line\n" * 2000
    for chunk in _chunk_for_codeblock(big):
        wrapped = _md_code_block(chunk)
        assert wrapped.startswith("```") and wrapped.endswith("```")


# --- /skills routing + /new inline keyboard ------------------------------

def test_skills_routes_to_cli_skills_list():
    assert SLASH_COMMANDS["skills"] == ["skills", "list"]


def test_new_sends_inline_keyboard():
    ch = _channel()
    asyncio.run(ch._on_command(_Update(723865496, "/new"), None))
    sent = ch._app.bot.sent
    assert len(sent) == 1
    kb = sent[0]["reply_markup"]
    assert kb is not None
    buttons = kb.inline_keyboard[0]
    assert {b.callback_data for b in buttons} == {NEW_CONFIRM, NEW_CANCEL}
    assert "clears the current chat history" in sent[0]["text"]


def test_new_confirm_clears_session():
    sessions = _FakeSessions(cleared=5)
    ch = _channel(sessions=sessions)
    upd = _CbUpdate(723865496, NEW_CONFIRM)
    asyncio.run(ch._on_callback(upd, None))
    assert upd.callback_query.answered
    assert sessions.called_with == "telegram:723865496"
    assert "New session started" in upd.callback_query.edited


def test_new_confirm_on_empty_session():
    ch = _channel(sessions=_FakeSessions(cleared=0))
    upd = _CbUpdate(723865496, NEW_CONFIRM)
    asyncio.run(ch._on_callback(upd, None))
    assert "already fresh" in upd.callback_query.edited


def test_new_cancel_keeps_history():
    sessions = _FakeSessions(cleared=9)
    ch = _channel(sessions=sessions)
    upd = _CbUpdate(723865496, NEW_CANCEL)
    asyncio.run(ch._on_callback(upd, None))
    assert sessions.called_with is None  # never cleared
    assert "Kept current history" in upd.callback_query.edited


def test_callback_from_non_allowed_chat_ignored():
    sessions = _FakeSessions(cleared=3)
    ch = _channel(sessions=sessions, allowed=("723865496",))
    upd = _CbUpdate(999999, NEW_CONFIRM)  # not in allowlist
    asyncio.run(ch._on_callback(upd, None))
    assert sessions.called_with is None
    assert upd.callback_query.edited is None


def test_callback_unknown_data_ignored():
    sessions = _FakeSessions(cleared=3)
    ch = _channel(sessions=sessions)
    upd = _CbUpdate(723865496, "bogus_data")
    asyncio.run(ch._on_callback(upd, None))
    assert sessions.called_with is None
    assert upd.callback_query.edited is None
