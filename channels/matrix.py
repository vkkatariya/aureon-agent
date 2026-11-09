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
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from collections import OrderedDict

from markdown_it import MarkdownIt
from mautrix.client import Client
from mautrix.errors import MUnknownToken
from mautrix.types import EventType, Membership, UserID

from channels.base import Channel
from aureon_agent.config import parse_csv_set
from channels.router import plain_confirmation_text
from channels.commands import SLASH_COMMANDS, run_cli

logger = logging.getLogger(__name__)

MATRIX_MAX_LEN = 15000          # split outbound messages above this
MATRIX_EDIT_MAX_LEN = 6000      # an m.replace edit carries 4 copies of the text (64KB event cap)
NEW_CONFIRM_TTL = 120           # seconds a !new confirmation stays pending
RECONNECT_MIN_SECONDS = 5
RECONNECT_MAX_SECONDS = 60
DEFAULT_PICKLE_KEY = "aureon-agent"   # override with MATRIX_PICKLE_KEY
RELOGIN_MAX = 3                 # password re-logins allowed per window (stops login loops)
RELOGIN_WINDOW_SECONDS = 600
TOKEN_STRIKES_BEFORE_RELOGIN = 2
CROSS_SIGN_TIMEOUT_SECONDS = 30
EDIT_THROTTLE_SECONDS = 1.0
DEDUPE_CACHE_SIZE = 1000
TYPING_TIMEOUT_MS = 10000
COMMAND_PREFIXES = ("!", "/")
CONFIRM_REACTIONS = {"✅": "yes", "👍": "yes", "❌": "no", "👎": "no"}
YES_WORDS = {"yes", "y", "confirm"}
NO_WORDS = {"no", "n", "cancel"}
MAX_EVENT_BYTES = 40000   # pre-encryption JSON budget; Megolm base64 adds ~33% (cap is 65536)
KNOWN_COMMANDS = set(SLASH_COMMANDS) | {"help", "new", "lesson"}

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


def event_size(content: dict) -> int:
    """Worst-case wire size: json.dumps escapes non-ASCII to 6-12 bytes per char."""
    return len(json.dumps(content).encode())


def split_to_fit(text: str, render, budget: int = MAX_EVENT_BYTES) -> list:
    """Split `text` (at newlines where possible) until every rendered event
    fits `budget` bytes. Returns [(piece, content), ...]. Character counts
    alone are not enough: non-ASCII text and HTML escaping both inflate size."""
    content = render(text)
    if event_size(content) <= budget or len(text) <= 1:
        return [(text, content)]
    mid = len(text) // 2
    cut = text.rfind("\n", 0, mid)
    if cut <= 0:
        cut = mid
    return (split_to_fit(text[:cut], render, budget)
            + split_to_fit(text[cut:].lstrip("\n") or text[cut:], render, budget))


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
    return parse_csv_set(value)


def db_has_account(db_path: str) -> bool:
    """True iff an Olm account row exists. Checked against the real table (not
    file size) so a half-created store from a failed first start isn't mistaken
    for a legacy one."""
    if not os.path.exists(db_path):
        return False
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            return conn.execute("SELECT COUNT(*) FROM crypto_account").fetchone()[0] > 0
    except sqlite3.Error:
        return False


class MatrixChannel(Channel):
    def __init__(self, homeserver, user_id, access_token, router, allowed_users,
                 device_id="AUREON_ARM64", home_room=None, encryption=True,
                 data_dir="data", pickle_key=None, password=None, env_path=None, recovery_key=None):
        self.homeserver = homeserver
        self.user_id = user_id
        self.access_token = access_token
        self.device_id = device_id
        self.allowed_users = parse_allowed_users(allowed_users)
        self.home_room = home_room
        self.encryption = encryption
        self.router = router
        self.data_dir = data_dir
        self.pickle_key = pickle_key or os.getenv("MATRIX_PICKLE_KEY")  # else resolved per install
        self.password = password             # enables self-heal when the token/device is revoked
        self.env_path = env_path             # where the rotated token/device id are persisted
        self._relogin_times = []
        self._relogin_disabled = False
        self._token_strikes = 0
        self.recovery_key = recovery_key     # cross-signs this device at start (SSSS recovery key)

        self.client = None
        self._crypto_db = None
        self._state_db = None
        self._seen = OrderedDict()           # event_id dedupe cache
        self._edit_locks = {}
        self._room_locks = {}
        self._pending_new = {}               # room_id -> monotonic expiry for !new
        self._confirm_events = {}            # room_id -> event_id of the open confirmation prompt
        self._sync_task = None
        self._supervisor = None
        self._stopping = False
        self._store_has_account = False
        self._started_ms = 0
        self._drop_old_events = False

    # ── lifecycle ─────────────────────────────────────────────────────────

    async def start(self):
        """Begin (and keep alive) the Matrix connection. Returns immediately;
        a supervisor task connects, runs the sync loop, and reconnects with
        backoff if startup fails (e.g. Tailscale not up yet) or sync dies."""
        self._started_ms = int(time.time() * 1000)
        self._stopping = False
        self._supervisor = asyncio.ensure_future(self._run_forever())

    async def _run_forever(self):
        delay = RECONNECT_MIN_SECONDS
        relogin = False
        while not self._stopping:
            try:
                await self._connect()
                self._token_strikes = 0
                delay = RECONNECT_MIN_SECONDS
                await self._sync_task
                if not self._stopping:
                    logger.error("matrix: sync loop ended unexpectedly; reconnecting")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("matrix: connection failed: %s — retrying in %ds", e, delay)
                if isinstance(e, MUnknownToken):
                    self._token_strikes += 1
                else:
                    self._token_strikes = 0
                # Two consecutive rejections before the destructive reset: one
                # M_UNKNOWN_TOKEN could be a transient homeserver fault.
                relogin = (self._token_strikes >= TOKEN_STRIKES_BEFORE_RELOGIN
                           and bool(self.password) and not self._relogin_disabled)
            finally:
                await self._teardown()
            if self._stopping:
                break
            if relogin:
                relogin = False
                try:
                    healed = await self._relogin()
                except Exception as e:  # noqa: BLE001 — never let self-heal kill the supervisor
                    logger.error("matrix: re-login crashed: %s", type(e).__name__)
                    healed = False
                if healed:
                    self._token_strikes = 0
                    delay = RECONNECT_MIN_SECONDS
                    continue
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_SECONDS)

    async def _relogin(self) -> bool:
        """Token/device was revoked (e.g. session removed in Element). Log in again
        with MATRIX_PASSWORD on a fresh device, persist the new credentials, then
        reset the crypto store (it belongs to the dead device). Rate-limited; never
        prints the password or token. Any failure returns False with the old
        credentials and store untouched."""
        now = time.monotonic()
        self._relogin_times = [t for t in self._relogin_times if now - t < RELOGIN_WINDOW_SECONDS]
        if len(self._relogin_times) >= RELOGIN_MAX:
            self._relogin_disabled = True
            logger.error("matrix: token revoked again, %d re-logins in %ds; self-heal disabled until restart",
                         RELOGIN_MAX, RELOGIN_WINDOW_SECONDS)
            return False
        self._relogin_times.append(now)
        base = re.sub(r"_[0-9A-F]{6}$", "", self.device_id)
        device = f"{base}_{secrets.token_hex(3).upper()}"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as http:
                r = await http.post(f"{self.homeserver.rstrip('/')}/_matrix/client/v3/login", json={
                    "type": "m.login.password",
                    "identifier": {"type": "m.id.user", "user": self.user_id},
                    "password": self.password, "device_id": device,
                    "initial_device_display_name": "aureon-agent"})
            if r.status_code != 200:
                code = r.json().get("errcode") if "json" in r.headers.get("content-type", "") else r.status_code
                logger.error("matrix: re-login failed (%s)", code)
                if code == "M_FORBIDDEN":
                    self._relogin_disabled = True   # wrong password: stop guessing
                return False
            data = r.json()
            if data.get("user_id") != self.user_id or not data.get("access_token"):
                logger.error("matrix: re-login returned an unexpected response")
                return False
        except Exception as e:  # noqa: BLE001 — network etc.; supervisor backs off
            logger.error("matrix: re-login failed: %s", type(e).__name__)
            return False
        new_token, new_device = data["access_token"], data.get("device_id", device)
        if not self._persist_credentials(new_token, new_device):
            return False   # keep old creds + store; otherwise every restart would re-login and wipe
        if self.encryption:
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.remove(os.path.join(self.data_dir, "matrix_crypto.db" + suffix))
                except FileNotFoundError:
                    pass
                except OSError as e:
                    logger.error("matrix: could not reset crypto store: %s", type(e).__name__)
                    return False
        self.access_token, self.device_id = new_token, new_device
        logger.warning("matrix: token was revoked; re-logged in as new device %s and reset the E2EE store",
                       self.device_id)
        return True

    def _persist_credentials(self, token, device) -> bool:
        if not self.env_path:
            return True
        try:
            from dotenv import set_key
            set_key(self.env_path, "MATRIX_ACCESS_TOKEN", token)
            set_key(self.env_path, "MATRIX_DEVICE_ID", device)
            os.chmod(self.env_path, 0o600)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("matrix: could not persist new credentials to %s: %s", self.env_path, type(e).__name__)
            return False

    async def _connect(self):
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
            # Must be decided before Database.start() creates the file.
            self._store_has_account = db_has_account(db_path)
            self._crypto_db = Database.create(url, upgrade_table=PgCryptoStore.upgrade_table)
            self._state_db = Database.create(url, upgrade_table=PgStateStore.upgrade_table)
            old_umask = os.umask(0o077)  # DB + -wal/-shm are created owner-only
            try:
                await self._crypto_db.start()
                await self._state_db.start()
            finally:
                os.umask(old_umask)
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.chmod(db_path + suffix, 0o600)
                except OSError:
                    pass
            crypto_store = PgCryptoStore(
                account_id=self.user_id,
                pickle_key=self.pickle_key or self._load_or_create_pickle_key(db_path),
                db=self._crypto_db,
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
            await self._cross_sign()
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
        logger.info("matrix: started as %s (device %s, e2ee=%s, %d allowed user(s))",
                    self.user_id, self.device_id, self.encryption, len(self.allowed_users))

    async def _cross_sign(self):
        """Sign this device with the account's cross-signing keys (fetched from SSSS
        via the recovery key) so Element shows it verified. Never blocks startup and
        never logs the key."""
        if not (self.recovery_key and self.client and self.client.crypto):
            return
        try:
            await asyncio.wait_for(
                self.client.crypto.verify_with_recovery_key(self.recovery_key.strip()),
                CROSS_SIGN_TIMEOUT_SECONDS)
            logger.info("matrix: device %s cross-signed", self.device_id)
        except Exception as e:  # noqa: BLE001 — verification is best-effort
            logger.error("matrix: cross-signing failed (%s); device stays unverified", type(e).__name__)

    def _load_or_create_pickle_key(self, db_path):
        """Per-install random pickle key in data/matrix_pickle.key (0600). A store
        that predates this keeps the legacy default (flagged by doctor) because
        its pickles can't be re-keyed in place."""
        key_path = os.path.join(self.data_dir, "matrix_pickle.key")
        if os.path.exists(key_path):
            with open(key_path) as f:
                return f.read().strip()
        # NB: the DB files are created before this runs (Database.start), so check
        # for an existing *account*, not mere file presence.
        if self._store_has_account:
            logger.warning("matrix: crypto store uses the legacy default pickle key; "
                           "set MATRIX_PICKLE_KEY or reset data/matrix_crypto.db* to harden it")
            return DEFAULT_PICKLE_KEY
        key = secrets.token_hex(32)
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(key)
        return key

    async def _upload_device_keys(self):
        """Best-effort device/one-time key upload. Non-fatal — Megolm E2EE works
        regardless. Verification is separate: see _cross_sign (needs
        MATRIX_RECOVERY_KEY); without it the device shows as unverified."""
        try:
            await self.client.crypto.share_keys()
        except Exception as e:
            logger.warning("matrix: key upload failed: %s", e)

    async def _teardown(self):
        """Release client, sync task and DBs. Idempotent; used between
        reconnect attempts and on stop()."""
        client, self.client = self.client, None
        sync_task, self._sync_task = self._sync_task, None
        dbs, self._crypto_db, self._state_db = (self._crypto_db, self._state_db), None, None
        if client is not None:
            try:
                client.stop()
            except Exception as e:
                logger.debug("matrix: client.stop failed: %s", e)
        if sync_task is not None:
            sync_task.cancel()
            try:
                await sync_task
            except BaseException:  # noqa: BLE001 — cancel/any sync error on teardown
                pass
        for db in dbs:
            if db is not None:
                try:
                    await db.stop()
                except Exception as e:
                    logger.debug("matrix: db stop failed: %s", e)
        if client is not None:
            try:
                await client.api.session.close()
            except Exception as e:
                logger.debug("matrix: session close failed: %s", e)

    async def stop(self):
        self._stopping = True
        if self._supervisor is not None:
            self._supervisor.cancel()
            try:
                await self._supervisor
            except BaseException:  # noqa: BLE001 — cancelled on shutdown
                pass
            self._supervisor = None
        await self._teardown()

    # ── outbound ──────────────────────────────────────────────────────────

    @staticmethod
    def _content(text: str, html_body: str | None = None) -> dict:
        return {
            "msgtype": "m.text",
            "body": text,
            "format": "org.matrix.custom.html",
            "formatted_body": html_body if html_body is not None else md_to_html(text),
        }

    async def send_message(self, chat_id, text, code=False, **_ignored):
        """Send text (Markdown rendered to HTML, or a <pre><code> block when
        code=True). Splits by character count and again by encoded event size.
        Returns the event_id of the first piece."""
        client = self.client
        if client is None:
            raise RuntimeError("matrix client not connected")
        render = ((lambda t: self._content(t, code_block_html(t))) if code
                  else (lambda t: self._content(t)))
        first = None
        for chunk in chunk_text(text or ""):
            for _piece, content in split_to_fit(chunk, render):
                eid = await client.send_message_event(chat_id, EventType.ROOM_MESSAGE, content)
                if first is None:
                    first = eid
        return first

    def _edit_content(self, message_id, text):
        new_content = self._content(text)
        return {
            "msgtype": "m.text",
            "body": f"* {text}",
            "format": "org.matrix.custom.html",
            "formatted_body": f"* {new_content['formatted_body']}",
            "m.new_content": new_content,
            "m.relates_to": {"rel_type": "m.replace", "event_id": message_id},
        }

    async def edit_message(self, chat_id, message_id, text):
        """Replace a message. Used for streaming partials, where dropping the tail
        is fine: the text is capped/shrunk to fit an event. The FINAL answer is
        pre-split with split_to_fit in _on_chat so nothing is lost."""
        text = (text or "…")[:MATRIX_EDIT_MAX_LEN]
        content = self._edit_content(message_id, text)
        while event_size(content) > MAX_EVENT_BYTES and len(text) > 1:
            text = text[: len(text) * 3 // 4]
            content = self._edit_content(message_id, text)
        try:
            await self.client.send_message_event(chat_id, EventType.ROOM_MESSAGE, content)
            return True
        except Exception as e:
            logger.warning("matrix: edit_message failed for %s/%s: %s", chat_id, message_id, e)
            return False

    async def send_confirmation(self, chat_id, text, confirm_data, cancel_data):
        """Native confirmation prompt (ChannelRouter.send_confirmation delegates
        here). Answer by typing yes/no, or by reacting ✅/❌ to *this* message."""
        body = plain_confirmation_text(text, extra=" Or react ✅ / ❌ to this message.")
        event_id = await self.send_message(chat_id, body)
        self._confirm_events[str(chat_id)] = str(event_id)
        return event_id

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
        room_id = str(evt.room_id)
        target = getattr(relates, "event_id", None)
        if target is None or str(target) != self._confirm_events.get(room_id):
            return  # reaction on some other message — not an answer to the prompt
        if self._resolve_confirm(room_id, answer):
            self._confirm_events.pop(room_id, None)

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

        expiry = self._pending_new.pop(room_id, None)
        if expiry is not None and time.monotonic() < expiry:
            answer = text.strip().lower()
            if answer in YES_WORDS or answer in NO_WORDS:
                await self._finish_new(room_id, answer in YES_WORDS)
                return
            # Anything else abandons the !new prompt and is handled normally.

        parsed = parse_command(text)
        if parsed is not None:
            cmd, args = parsed
            # `!` is unambiguously a command; a leading `/` only is when it names
            # a known command (so "/etc/fstab why..." still reaches the LLM).
            if text.lstrip().startswith("!") or cmd in KNOWN_COMMANDS:
                await self._on_command(room_id, cmd, args)
                return

        await self._on_chat(room_id, text)

    def _has_pending_prompt(self, room_id) -> bool:
        session = f"matrix:{room_id}"
        for name in ("pending_confirmations", "pending_clarifications"):
            fut = (getattr(self.router, name, None) or {}).get(session)
            if fut is not None and not fut.done():
                return True
        return False

    async def _on_chat(self, room_id, text):
        if self._has_pending_prompt(room_id):
            # The reply answers an open confirmation/clarification; the router
            # consumes it (returns None), so don't post a placeholder for it.
            await self.router.handle_message("matrix", room_id, text, {})
            self._confirm_events.pop(room_id, None)
            return

        # mautrix runs each event as its own task; serialize agent runs per room so
        # two quick messages don't interleave on one session (Telegram is sequential).
        async with self._room_locks.setdefault(room_id, asyncio.Lock()):
            await self._run_chat(room_id, text)

    async def _run_chat(self, room_id, text):
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

        # The first piece replaces the placeholder (an edit carries 4 copies of the
        # text, so size it with the edit renderer); the rest go out as new messages.
        pieces = split_to_fit(response, lambda t: self._edit_content(placeholder, t))
        first = pieces[0][0]
        if not await self.edit_message(room_id, placeholder, first):
            await self.send_message(room_id, first)  # never lose the final answer
        for piece, _content in pieces[1:]:
            await self.send_message(room_id, piece)

    # ── commands ──────────────────────────────────────────────────────────

    async def _on_command(self, room_id, cmd, args):
        logger.info("matrix._on_command: room=%s cmd=%s", room_id, cmd)

        if cmd == "help":
            lines = ["**Available commands** (`!` or `/` prefix):", ""]
            lines += [f"- `!{name}` — {desc}" for name, desc in HELP_COMMANDS]
            await self.send_message(room_id, "\n".join(lines))
            return

        if cmd == "new":
            self._pending_new[room_id] = time.monotonic() + NEW_CONFIRM_TTL
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
        out = await run_cli(cmd, cli_args, "")
        await self._stop_typing(room_id)
        for chunk in chunk_text(out, MATRIX_MAX_LEN - 1000):
            await self.send_message(room_id, chunk, code=True)

    async def _finish_new(self, room_id, confirmed):
        if not confirmed:
            await self.send_message(room_id, "Kept current history.")
            return
        cleared = await self.router.sessions.clear_session(f"matrix:{room_id}")
        if cleared:
            await self.send_message(room_id, f"✅ New session started. Cleared {cleared} message(s).")
        else:
            await self.send_message(room_id, "✅ New session — chat already fresh.")
