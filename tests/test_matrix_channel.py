"""MatrixChannel logic tests with a fake mautrix client (no network, no crypto)."""
import asyncio
from types import SimpleNamespace

from mautrix.types import EventType, Membership

from channels import matrix as mx
from channels.matrix import MatrixChannel, chunk_text, code_block_html, md_to_html, parse_command

BOT = "@aureon-agent:example.org"
OWNER = "@owner:example.org"
ROOM = "!room:example.org"


class FakeClient:
    def __init__(self):
        self.events = []   # (room_id, event_type, content)
        self.typing = []
        self.joined = []
        self.left = []

    async def send_message_event(self, room_id, event_type, content):
        self.events.append((room_id, event_type, content))
        return f"$ev{len(self.events)}"

    async def set_typing(self, room_id, timeout=0):
        self.typing.append((room_id, timeout))

    async def join_room(self, room_id):
        self.joined.append(room_id)

    async def leave_room(self, room_id):
        self.left.append(room_id)


class FakeSessions:
    def __init__(self):
        self.cleared = []

    async def clear_session(self, session_id):
        self.cleared.append(session_id)
        return 3


class FakeRouter:
    def __init__(self, response="hello back", tokens=()):
        self.calls = []
        self.response = response
        self.tokens = tokens
        self.sessions = FakeSessions()
        self.pending_confirmations = {}

    async def handle_message(self, channel, client_id, text, callbacks):
        self.calls.append((channel, client_id, text))
        for t in self.tokens:
            await callbacks["on_token"](t)
        return self.response


def make(router=None, **kw):
    ch = MatrixChannel(
        homeserver="https://hs.example.org", user_id=BOT, access_token="tok",
        router=router or FakeRouter(), allowed_users=kw.pop("allowed", {OWNER}),
        encryption=False, **kw)
    ch.client = FakeClient()
    return ch


_n = [0]


def msg(sender=OWNER, body="hi", room=ROOM, msgtype="m.text", relates_to=None, ts=None, event_id=None):
    _n[0] += 1
    return SimpleNamespace(
        sender=sender, room_id=room, event_id=event_id or f"$e{_n[0]}", timestamp=ts,
        content=SimpleNamespace(msgtype=msgtype, body=body, relates_to=relates_to))


def sent_bodies(ch):
    return [c["body"] for _, _, c in ch.client.events if "m.relates_to" not in c]


def run(coro):
    return asyncio.run(coro)


# ── allowlist / dedupe ────────────────────────────────────────────────────

def test_foreign_sender_dropped_silently():
    ch = make()
    run(ch._on_message(msg(sender="@stranger:example.org", body="hello")))
    assert ch.router.calls == [] and ch.client.events == []


def test_own_messages_ignored():
    ch = make(allowed={OWNER, BOT})
    run(ch._on_message(msg(sender=BOT, body="echo")))
    assert ch.router.calls == []


def test_duplicate_event_processed_once():
    ch = make()
    e = msg(body="hello", event_id="$same")
    run(ch._on_message(e))
    run(ch._on_message(e))
    assert len(ch.router.calls) == 1


def test_dedupe_cache_bounded():
    ch = make()
    for i in range(mx.DEDUPE_CACHE_SIZE + 50):
        ch._is_duplicate(f"$e{i}")
    assert len(ch._seen) == mx.DEDUPE_CACHE_SIZE
    assert not ch._is_duplicate("$e0")  # evicted, treated as new


def test_old_events_dropped_when_no_sync_token():
    ch = make()
    ch._started_ms = 1_000_000
    ch._drop_old_events = True
    run(ch._on_message(msg(body="old", ts=500_000)))
    run(ch._on_message(msg(body="new", ts=1_000_500)))
    assert [c[2] for c in ch.router.calls] == ["new"]


def test_edits_and_non_text_ignored():
    ch = make()
    run(ch._on_message(msg(body="* edited", relates_to=SimpleNamespace(rel_type="m.replace"))))
    run(ch._on_message(msg(msgtype="m.image", body="pic.png")))
    assert ch.router.calls == []


# ── invites ───────────────────────────────────────────────────────────────

def _invite(sender):
    return SimpleNamespace(state_key=BOT, sender=sender, room_id=ROOM,
                           content=SimpleNamespace(membership=Membership.INVITE))


def test_invite_from_allowed_user_joined():
    ch = make()
    run(ch._on_member(_invite(OWNER)))
    assert ch.client.joined == [ROOM] and ch.client.left == []


def test_invite_from_stranger_rejected():
    ch = make()
    run(ch._on_member(_invite("@stranger:example.org")))
    assert ch.client.joined == [] and ch.client.left == [ROOM]


def test_member_event_for_other_user_ignored():
    ch = make()
    evt = _invite(OWNER)
    evt.state_key = "@someone-else:example.org"
    run(ch._on_member(evt))
    assert ch.client.joined == [] and ch.client.left == []


# ── commands ──────────────────────────────────────────────────────────────

def test_dual_prefix_parse_identical():
    assert parse_command("!status") == parse_command("/status") == ("status", "")
    assert parse_command("!lesson be careful") == ("lesson", "be careful")
    assert parse_command("plain text") is None
    assert parse_command("!") is None


def test_status_via_bang_and_slash_route_identically(monkeypatch):
    calls = []

    async def fake_cli(cmd, cli_args):
        calls.append((cmd, cli_args))
        return "OUTPUT <b>"

    monkeypatch.setattr(MatrixChannel, "_run_cli", staticmethod(fake_cli))
    for prefix in ("!", "/"):
        ch = make()
        run(ch._on_message(msg(body=f"{prefix}status")))
        assert ch.router.calls == []          # no LLM
        _, _, content = ch.client.events[-1]
        assert content["formatted_body"] == "<pre><code>OUTPUT &lt;b&gt;</code></pre>"
    assert calls == [("status", ["status"])] * 2


def test_unknown_command_reply():
    ch = make()
    run(ch._on_message(msg(body="!bogus")))
    assert "Unknown command" in sent_bodies(ch)[0]


def test_help_lists_commands():
    ch = make()
    run(ch._on_message(msg(body="!help")))
    body = sent_bodies(ch)[0]
    for name in ("new", "status", "doctor", "skills"):
        assert f"!{name}" in body


def test_new_requires_typed_confirmation_then_clears():
    ch = make()
    run(ch._on_message(msg(body="!new")))
    assert ch.router.sessions.cleared == []
    run(ch._on_message(msg(body="yes")))
    assert ch.router.sessions.cleared == [f"matrix:{ROOM}"]
    assert ch.router.calls == []


def test_new_cancelled_by_other_reply():
    ch = make()
    run(ch._on_message(msg(body="/new")))
    run(ch._on_message(msg(body="nope")))
    assert ch.router.sessions.cleared == []
    assert "Kept" in sent_bodies(ch)[-1]
    assert ch.router.calls == []


def test_lesson_routes_through_router():
    ch = make(router=FakeRouter(response="Logged to lessons.md."))
    run(ch._on_message(msg(body="!lesson check imports")))
    assert ch.router.calls == [("matrix", ROOM, "/lesson check imports")]


# ── streaming / outbound ──────────────────────────────────────────────────

def test_chat_streams_via_edits_and_final_edit():
    ch = make(router=FakeRouter(response="final answer", tokens=["a", "b", "c"]))
    run(ch._on_message(msg(body="hello")))
    assert ch.router.calls == [("matrix", ROOM, "hello")]
    first = ch.client.events[0][2]
    assert first["body"] == "…"
    edits = [c for _, _, c in ch.client.events if "m.relates_to" in c]
    last = edits[-1]
    assert last["m.relates_to"] == {"rel_type": "m.replace", "event_id": "$ev1"}
    assert last["m.new_content"]["body"] == "final answer"
    assert last["body"] == "* final answer"


def test_edit_throttled_to_one_per_second():
    ch = make(router=FakeRouter(response="done", tokens=list("abcdefghij")))
    run(ch._on_message(msg(body="hello")))
    # Rapid tokens: at most 1 streaming edit (first token) + 1 final edit.
    edits = [c for _, _, c in ch.client.events if "m.relates_to" in c]
    assert len(edits) <= 2


def test_long_response_chunked():
    big = ("x" * 99 + "\n") * 400   # 40K chars
    ch = make(router=FakeRouter(response=big))
    run(ch._on_message(msg(body="hello")))
    bodies = [c.get("m.new_content", c)["body"] for _, _, c in ch.client.events[1:]]
    assert len(bodies) >= 3
    assert all(len(b) <= mx.MATRIX_MAX_LEN for b in bodies)


def test_chunk_text_boundaries():
    assert chunk_text("short") == ["short"]
    text = "a" * 40000
    chunks = chunk_text(text, 15000)
    assert [len(c) for c in chunks] == [15000, 15000, 10000]
    assert "".join(chunks) == text


def test_send_message_html_and_return_id():
    ch = make()
    eid = run(ch.send_message(ROOM, "**bold** and `code`"))
    assert eid == "$ev1"
    content = ch.client.events[0][2]
    assert content["format"] == "org.matrix.custom.html"
    assert "<strong>bold</strong>" in content["formatted_body"]
    assert "<code>code</code>" in content["formatted_body"]
    assert ch.client.events[0][1] == EventType.ROOM_MESSAGE


def test_raw_html_in_markdown_escaped():
    assert "<script>" not in md_to_html("<script>alert(1)</script>")
    assert code_block_html("<&>") == "<pre><code>&lt;&amp;&gt;</code></pre>"


def test_send_action_typing():
    ch = make()
    run(ch.send_action(ROOM, "typing"))
    assert ch.client.typing == [(ROOM, mx.TYPING_TIMEOUT_MS)]


# ── confirmations ─────────────────────────────────────────────────────────

def test_typed_yes_resolves_pending_confirmation_via_router():
    # Plain replies flow to router.handle_message, which owns resolution.
    ch = make()
    run(ch._on_message(msg(body="yes")))
    assert ch.router.calls == [("matrix", ROOM, "yes")]


def test_reaction_resolves_pending_confirmation():
    async def go():
        router = FakeRouter()
        ch = make(router=router)
        fut = asyncio.get_running_loop().create_future()
        router.pending_confirmations[f"matrix:{ROOM}"] = fut
        evt = SimpleNamespace(sender=OWNER, room_id=ROOM, event_id="$r1",
                              content=SimpleNamespace(relates_to=SimpleNamespace(key="✅")))
        await ch._on_reaction(evt)
        return fut.result()
    assert run(go()) == "yes"


def test_reaction_from_stranger_ignored():
    async def go():
        router = FakeRouter()
        ch = make(router=router)
        fut = asyncio.get_running_loop().create_future()
        router.pending_confirmations[f"matrix:{ROOM}"] = fut
        evt = SimpleNamespace(sender="@stranger:example.org", room_id=ROOM, event_id="$r2",
                              content=SimpleNamespace(relates_to=SimpleNamespace(key="✅")))
        await ch._on_reaction(evt)
        return fut.done()
    assert run(go()) is False
