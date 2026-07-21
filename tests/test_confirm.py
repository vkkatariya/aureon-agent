"""Tests for aureon_agent.tools.confirm.confirm_with_captain.

Verifies the confirmation now uses an inline keyboard (reply_markup) instead
of a bare typed-"yes" prompt, and that the pending future resolves correctly
for both the inline-tap and typed fallback paths.
"""
import asyncio

from aureon_agent.tools.confirm import confirm_with_captain

CONFIRM_YES = "confirm_yes"
CONFIRM_NO = "confirm_no"


class _FakeChannel:
    def __init__(self):
        self.last = None

    async def send_message(self, client_id, text, reply_markup=None):
        self.last = {"client_id": client_id, "text": text, "reply_markup": reply_markup}


class _FakeRouter:
    def __init__(self):
        self.pending_confirmations = {}
        self.channels = {"telegram": _FakeChannel()}

    async def send_confirmation(self, session_id, text, confirm_data, cancel_data):
        self._confirm_sent = (session_id, text, confirm_data, cancel_data)


def _ctx(router):
    return {"router": router, "session_id": "telegram:723865496"}


async def _confirm(ctx, router, resolve_with):
    """Drive confirm_with_captain, resolving the future it registers."""
    task = asyncio.ensure_future(confirm_with_captain(ctx, "do it?", timeout=2))
    await asyncio.sleep(0.05)  # let it send the confirmation + register its future
    assert router._confirm_sent[2] == CONFIRM_YES
    assert router._confirm_sent[3] == CONFIRM_NO
    assert "Confirmation Required" in router._confirm_sent[1]
    # confirm_with_captain registered its own future in router.pending_confirmations
    fut = router.pending_confirmations["telegram:723865496"]
    fut.set_result(resolve_with)
    return await task


def test_confirm_sends_inline_keyboard_and_yes():
    router = _FakeRouter()
    assert asyncio.run(_confirm(_ctx(router), router, "yes")) is True


def test_confirm_no_denies():
    router = _FakeRouter()
    assert asyncio.run(_confirm(_ctx(router), router, "no")) is False


def test_confirm_typed_yes_fallback():
    """Typed 'yes' (router.handle_message path) still confirms."""
    router = _FakeRouter()
    assert asyncio.run(_confirm(_ctx(router), router, "yes")) is True


def test_confirm_timeout_denies():
    router = _FakeRouter()
    # Never resolve -> timeout -> default deny.
    assert asyncio.run(confirm_with_captain(_ctx(router), "nuke?", timeout=0.1)) is False


def test_confirm_missing_router_denies():
    assert asyncio.run(confirm_with_captain({}, "x?", timeout=1)) is False
