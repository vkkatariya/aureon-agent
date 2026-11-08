"""Matrix adapter (mautrix): self-hosted Conduit homeserver, MXID allowlist,
optional Megolm E2EE (SQLite crypto store), streaming via m.replace edits
throttled to 1 edit/sec, HTML-formatted output, and `!`/`/` command surface.

Element intercepts a leading `/` as a client-side command, so `!` is the
primary prefix (`!status`, `!doctor`, ...). `/` stays as a backward-compatible
alias for clients that pass it through.

Security: only MXIDs in `allowed_users` can talk to the bot or invite it to a
room. Everything else is dropped silently.
"""
import asyncio
import html
import logging
import os
import subprocess
import sys
import time
from collections import OrderedDict

from markdown_it import MarkdownIt
from mautrix.client import Client
from mautrix.types import EventType, Membership, UserID

from channels.base import Channel
from channels.telegram import SLASH_COMMANDS

logger = logging.getLogger(__name__)

MATRIX_MAX_LEN = 15000          # split outbound messages above this
EDIT_THROTTLE_SECONDS = 1.0
DEDUPE_CACHE_SIZE = 1000
TYPING_TIMEOUT_MS = 10000
COMMAND_PREFIXES = ("!", "/")
CONFIRM_REACTIONS = {"✅": "yes", "👍": "yes", "❌": "no", "👎": "no"}
YES_WORDS = {"yes", "y", "confirm"}

HELP_COMMANDS = [
    ("new", "start a new session (clears history)"),
    ("skills", "list loaded doctrine skills"),
    ("sessions", "list all chat sessions"),
    ("doctor", "health checks"),
    ("status", "agent status"),
    ("mcp", "list MCP servers + tools"),
    ("cron", "list cron jobs"),
    ("logs", "recent bot logs"),
    ("version", "agent version"),
    ("lesson <text>", "record a lesson"),
    ("help", "this message"),
]

_md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")


def md_to_html(text: str) -> str:
    """Render Markdown to Matrix-safe HTML (raw HTML in the source is escaped)."""
    return _md.render(text).strip()


def code_block_html(text: str) -> str:
    """Wrap CLI output in <pre><code> so Element renders aligned monospace."""
    return f"<pre><code>{html.escape(text)}</code></pre>"


def chunk_text(text: str, limit: int = MATRIX_MAX_LEN) -> list:
    """Split text into pieces of at most `limit` chars, preferring newline breaks."""
    if len(text) <= limit:
        return [text]
    chunks = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip("\n") if cut != limit else rest[cut:]
    if rest:
        chunks.append(rest)
    return chunks


def parse_command(text: str):
    """Return (cmd, args) when text starts with `!` or `/`, else None.
    `!status` and `/status` parse identically."""
    stripped = text.strip()
    if not stripped or stripped[0] not in COMMAND_PREFIXES:
        return None
    parts = stripped[1:].split(None, 1)
    if not parts:
        return None
    return parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")


def parse_allowed_users(value) -> set:
    if isinstance(value, (set, frozenset, list, tuple)):
        return {str(u).strip() for u in value if str(u).strip()}
    return {u.strip() for u in (value or "").split(",") if u.strip()}


class MatrixChannel(Channel):
    def __init__(self, homeserver, user_id, access_token, router, allowed_users,
                 device_id="AUREON_ARM64", home_room=None, encryption=True,
                 data_dir="data"):
        self.homeserver = homeserver
        self.user_id = user_id
        self.access_token = access_token
        self.device_id = device_id
        self.allowed_users = parse_allowed_users(allowed_users)
        self.home_room = home_room
        self.encryption = encryption
        self.router = router
        self.data_dir = data_dir

        self.client = None
        self._crypto_db = None
        self._state_db = None
        self._seen = OrderedDict()           # event_id dedupe cache
        self._edit_locks = {}
        self._pending_new = set()            # rooms awaiting !new confirmation
        self._sync_task = None
        self._started_ms = 0
        self._drop_old_events = False

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def start(self):
        self._started_ms = int(time.time() * 1000)
        sync_store = None
        state_store = None
        crypto_store = None

        if self.encryption:
            from mautrix.client.state_store.asyncpg import PgStateStore
            from mautrix.crypto import OlmMachine
            from mautrix.crypto.store.asyncpg import PgCryptoStore
            from mautrix.util.async_db import Database

            os.makedirs(self.data_dir, exist_ok=True)
            db_path = os.path.join(self.data_dir, "matrix_crypto.db")
            url = f"sqlite:{db_path}"
            self._crypto_db = Database.create(url, upgrade_table=PgCryptoStore.upgrade_table)
            self._state_db = Database.create(url, upgrade_table=PgStateStore.upgrade_table)
            await self._crypto_db.start()
            await self._state_db.start()
            try:
                os.chmod(db_path, 0o600)
            except OSError:
                pass
            crypto_store = PgCryptoStore(
                account_id=self.user_id, pickle_key="aureon-agent", db=self._crypto_db,
            )
            state_store = PgStateStore(self._state_db)
            sync_store = crypto_store

        self.client = Client(
            base_url=self.homeserver,
            mxid=UserID(self.user_id),
            token=self.access_token,
            device_id=self.device_id,
            sync_store=sync_store,
            state_store=state_store,
        )

        who = await self.client.whoami()
        if who.user_id != self.user_id:
            raise RuntimeError(
                f"Matrix access token belongs to {who.user_id}, expected {self.user_id}")
        if who.device_id:
            self.client.device_id = who.device_id
            self.device_id = who.device_id

        if self.encryption:
            stored_device = await crypto_store.get_device_id()
            if stored_device and stored_device != self.device_id:
                raise RuntimeError(
                    f"Crypto store belongs to device {stored_device}, but the access token "
                    f"is for {self.device_id}. Remove data/matrix_crypto.db* to reset E2EE state.")
            await crypto_store.put_device_id(self.device_id)
            self.client.crypto = OlmMachine(self.client, crypto_store, state_store)
            await self.client.crypto.load()
            await self._upload_device_keys()
            token = await crypto_store.get_next_batch()
        else:
            token = None
        # Without a persisted sync token the first sync replays room history;
        # drop anything older than startup so old messages don't trigger replies.
        self._drop_old_events = not token

        self.client.add_event_handler(EventType.ROOM_MEMBER, self._on_member)
        self.client.add_event_handler(EventType.ROOM_MESSAGE, self._on_message)
        self.client.add_event_handler(EventType.REACTION, self._on_reaction)

        self._sync_task = asyncio.ensure_future(self.client.start(None))
        self._sync_task.add_done_callback(self._on_sync_done)
        logger.info("matrix: started as %s (device %s, e2ee=%s, %d allowed user(s))",
                    self.user_id, self.device_id, self.encryption, len(self.allowed_users))

    async def _upload_device_keys(self):
        """Best-effort device/one-time key upload. Cross-signing is deliberately
        not bootstrapped: Conduit 0.10 answers its UIA step with 401 (mautrix UIA
        gap). Non-fatal — per-room/DM Megolm E2EE works regardless; the bot's
        device just shows as unverified in Element."""
        try:
            await self.client.crypto.share_keys()
        except Exception as e:
            logger.warning("matrix: key upload failed: %s", e)

    @staticmethod
    def _on_sync_done(task):
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("matrix: sync loop ended with error: %s", exc)

    async def stop(self):
        if self.client is not None:
            try:
                self.client.stop()
            except Exception as e:
                logger.debug("matrix: client.stop failed: %s", e)
        if self._sync_task is not None:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except BaseException:  # noqa: BLE001 — cancel/any sync error on shutdown
                pass
        for db in (self._crypto_db, self._state_db):
            if db is not None:
                try:
                    await db.stop()
                except Exception as e:
                    logger.debug("matrix: db stop failed: %s", e)
        if self.client is not None:
            try:
                await self.client.api.session.close()
            except Exception as e:
                logger.debug("matrix: session close failed: %s", e)

    # ── outbound ──────────────────────────────────────────────────────────

    @staticmethod
    def _content(text: str, html_body: str | None = None) -> dict:
        return {
            "msgtype": "m.text",
            "body": text,
            "format": "org.matrix.custom.html",
            "formatted_body": html_body if html_body is not None else md_to_html(text),
        }

    async def send_message(self, chat_id, text, html_body=None, **_ignored):
        """Send text (Markdown rendered to HTML). Splits above MATRIX_MAX_LEN.
        Returns the event_id of the first chunk."""
        first = None
        for chunk in chunk_text(text or ""):
            eid = await self.client.send_message_event(
                chat_id, EventType.ROOM_MESSAGE,
                self._content(chunk, html_body if first is None and html_body else None),
            )
            if first is None:
                first = eid
        return first

    async def edit_message(self, chat_id, message_id, text):
        text = (text or "…")[:MATRIX_MAX_LEN]
        new_content = self._content(text)
        content = {
            "msgtype": "m.text",
            "body": f"* {text}",
            "format": "org.matrix.custom.html",
            "formatted_body": f"* {new_content['formatted_body']}",
            "m.new_content": new_content,
            "m.relates_to": {"rel_type": "m.replace", "event_id": message_id},
        }
        try:
            await self.client.send_message_event(chat_id, EventType.ROOM_MESSAGE, content)
        except Exception as e:
            logger.debug("matrix: edit_message skipped for %s/%s: %s", chat_id, message_id, e)

    async def send_action(self, chat_id, action):
        if action == "typing":
            try:
                await self.client.set_typing(chat_id, timeout=TYPING_TIMEOUT_MS)
            except Exception as e:
                logger.debug("matrix: set_typing failed: %s", e)

    async def _stop_typing(self, chat_id):
        try:
            await self.client.set_typing(chat_id, timeout=0)
        except Exception as e:
            logger.debug("matrix: stop typing failed: %s", e)

    # ── inbound ───────────────────────────────────────────────────────────

    def _is_allowed(self, sender) -> bool:
        return str(sender) in self.allowed_users

    def _is_duplicate(self, event_id) -> bool:
        if event_id is None:
            return False
        key = str(event_id)
        if key in self._seen:
            return True
        self._seen[key] = None
        while len(self._seen) > DEDUPE_CACHE_SIZE:
            self._seen.popitem(last=False)
        return False

    async def _on_member(self, evt):
        """Auto-join invites from allowed users; reject everyone else."""
        if str(getattr(evt, "state_key", "")) != self.user_id:
            return
        content = evt.content
        if getattr(content, "membership", None) != Membership.INVITE:
            return
        sender = str(evt.sender)
        room_id = evt.room_id
        if not self._is_allowed(sender):
            logger.info("matrix: rejecting invite to %s from non-allowed user", room_id)
            try:
                await self.client.leave_room(room_id)
            except Exception as e:
                logger.debug("matrix: reject invite failed: %s", e)
            return
        try:
            await self.client.join_room(room_id)
            logger.info("matrix: joined %s (invited by %s)", room_id, sender)
        except Exception as e:
            logger.warning("matrix: join %s failed: %s", room_id, e)

    async def _on_reaction(self, evt):
        sender = str(evt.sender)
        if sender == self.user_id or not self._is_allowed(sender):
            return
        if self._is_duplicate(getattr(evt, "event_id", None)):
            return
        relates = getattr(evt.content, "relates_to", None)
        answer = CONFIRM_REACTIONS.get((getattr(relates, "key", "") or "").strip("️"))
        if answer is None:
            return
        self._resolve_confirm(str(evt.room_id), answer)

    def _resolve_confirm(self, room_id, result) -> bool:
        pending = getattr(self.router, "pending_confirmations", None) or {}
        future = pending.get(f"matrix:{room_id}")
        if future and not future.done():
            future.set_result(result)
            return True
        return False

    def _should_skip(self, evt) -> bool:
        sender = str(evt.sender)
        if sender == self.user_id:
            return True
        if not self._is_allowed(sender):
            return True  # silent drop
        if self._is_duplicate(getattr(evt, "event_id", None)):
            return True
        if self._drop_old_events:
            ts = getattr(evt, "timestamp", None)
            if ts is not None and ts < self._started_ms - 2000:
                return True
        return False

    async def _on_message(self, evt):
        if self._should_skip(evt):
            return
        content = evt.content
        if str(getattr(content, "msgtype", "")) != "m.text":
            return
        relates = getattr(content, "relates_to", None)
        if relates is not None and str(getattr(relates, "rel_type", "")) == "m.replace":
            return  # someone's edit of an earlier message
        text = (getattr(content, "body", "") or "").strip()
        if not text:
            return
        room_id = str(evt.room_id)

        if room_id in self._pending_new:
            self._pending_new.discard(room_id)
            await self._finish_new(room_id, text)
            return

        parsed = parse_command(text)
        if parsed is not None:
            await self._on_command(room_id, *parsed)
            return

        await self._on_chat(room_id, text)

    async def _on_chat(self, room_id, text):
        placeholder = await self.send_message(room_id, "…")
        lock = self._edit_locks.setdefault(room_id, asyncio.Lock())
        state = {"text": "", "last_edit": 0.0}

        async def on_token(token):
            state["text"] += token
            now = time.monotonic()
            if now - state["last_edit"] < EDIT_THROTTLE_SECONDS:
                return
            async with lock:
                state["last_edit"] = now
                await self.edit_message(room_id, placeholder, state["text"])

        async def on_tool_use(_name, _args):
            await self.send_action(room_id, "typing")

        try:
            response = await self.router.handle_message(
                "matrix", room_id, text, {"on_token": on_token, "on_tool_use": on_tool_use},
            )
        except Exception as e:
            await self._stop_typing(room_id)
            await self.edit_message(room_id, placeholder, f"Error: {e}")
            return
        await self._stop_typing(room_id)

        if not response:
            if state["text"].strip():
                await self.edit_message(room_id, placeholder, state["text"])
            else:
                await self.edit_message(room_id, placeholder, "(no response)")
            return

        chunks = chunk_text(response)
        await self.edit_message(room_id, placeholder, chunks[0])
        for chunk in chunks[1:]:
            await self.send_message(room_id, chunk)

    # ── commands ──────────────────────────────────────────────────────────

    async def _on_command(self, room_id, cmd, args):
        logger.info("matrix._on_command: room=%s cmd=%s", room_id, cmd)

        if cmd == "help":
            lines = ["**Available commands** (`!` or `/` prefix):", ""]
            lines += [f"- `!{name}` — {desc}" for name, desc in HELP_COMMANDS]
            await self.send_message(room_id, "\n".join(lines))
            return

        if cmd == "new":
            self._pending_new.add(room_id)
            await self.send_message(
                room_id,
                f"Start a new session? This clears the current chat history "
                f"(matrix:{room_id}). Cannot be undone.\n\nReply **yes** to confirm "
                f"or anything else to cancel.",
            )
            return

        if cmd == "lesson":
            if not args:
                await self.send_message(room_id, "Usage: `!lesson <what to remember>`")
                return
            reply = await self.router.handle_message("matrix", room_id, f"/lesson {args}", {})
            await self.send_message(room_id, reply or "Logged to lessons.md.")
            return

        cli_args = SLASH_COMMANDS.get(cmd)
        if not cli_args:
            await self.send_message(room_id, f"Unknown command: `!{cmd}` — try `!help`.")
            return

        await self.send_action(room_id, "typing")
        out = await self._run_cli(cmd, cli_args)
        await self._stop_typing(room_id)
        for chunk in chunk_text(out, MATRIX_MAX_LEN - 1000):
            await self.send_message(room_id, chunk, html_body=code_block_html(chunk))

    @staticmethod
    async def _run_cli(cmd, cli_args) -> str:
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, "-m", "aureon_agent.__main__", *cli_args],
                capture_output=True, text=True, timeout=60,
            )
            out = (proc.stdout or proc.stderr or "").strip()
        except Exception as e:
            out = f"Error running !{cmd}: {e}"
        return out or f"(!{cmd} produced no output)"

    async def _finish_new(self, room_id, reply):
        if reply.strip().lower() not in YES_WORDS:
            await self.send_message(room_id, "Kept current history.")
            return
        cleared = await self.router.sessions.clear_session(f"matrix:{room_id}")
        if cleared:
            await self.send_message(room_id, f"✅ New session started. Cleared {cleared} message(s).")
        else:
            await self.send_message(room_id, "✅ New session — chat already fresh.")
