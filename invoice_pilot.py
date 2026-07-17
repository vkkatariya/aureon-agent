#!/usr/bin/env python3
"""Engine A — standalone Gmail invoice auto-downloader.

Searches a Gmail inbox for invoice emails, downloads the PDF/image
attachments, and saves them to a folder. Self-contained: talks to the
Gmail REST API directly via an OAuth refresh token (no agent, no MCP).

Invoice recognition is a deterministic heuristic (Gmail search + filename
type gate), not an LLM — faster, cheaper, reproducible.

Rate-limit engineering is the centrepiece: candidates are fetched via a
search-first query (~20x fewer calls than scanning the whole mailbox),
processed in throttled batches, with exponential 429 backoff that honours
`Retry-After`, and a `.seen.json` checkpoint written every batch so a crash
resumes without re-downloading.

Auth (no secrets in repo):
  - refresh_token  ← tokens/<account>.json   (gitignored)
  - client id/secret ← .env GOOGLE_OAUTH_CLIENT_ID / _SECRET (gitignored)

Usage:
  python invoice_pilot.py --dry-run
  python invoice_pilot.py --dir ~/dev-shared/docs/invoices
  python invoice_pilot.py --before 2026/01/01          # oldest -> boundary
  python invoice_pilot.py --incremental                # weekly cron window
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("invoice_pilot")

# --- config / heuristics -------------------------------------------------

DEFAULT_QUERY = "subject:(invoice OR rechnung OR facture) has:attachment"
DEFAULT_DIR = "~/dev-shared/docs/invoices"
DEFAULT_ACCOUNT = "vishal"

# Attachment type gate: only these are downloadable documents.
DOC_EXT_RE = re.compile(r"\.(pdf|png|jpe?g)$", re.I)
# Invoice-name signal (D3). Applied only in --strict mode; by default the
# invoice-subject search is trusted and every document attachment is taken.
INVOICE_NAME_RE = re.compile(r"rechnung|invoice|factur|账单", re.I)

# Rate-limit defense (§4 of the kickoff).
BATCH_SIZE = 50
THROTTLE_SECONDS = 6      # sleep between batches -> ~5000 u/min (< 6000 cap)
MAX_RETRIES = 5
BACKOFF_BASE = 1.0        # 1s -> 2s -> 4s ...
BACKOFF_CAP = 30.0

USER_ID = "me"
TOKEN_URI = "https://oauth2.googleapis.com/token"


# --- attachment / filename helpers --------------------------------------

def is_document(filename: str) -> bool:
    """True if the attachment is a downloadable document type."""
    return bool(filename) and bool(DOC_EXT_RE.search(filename))


def looks_like_invoice(filename: str) -> bool:
    """True if the filename itself carries an invoice token (D3 strict gate)."""
    return bool(filename) and bool(INVOICE_NAME_RE.search(filename))


def should_download(filename: str, strict: bool = False) -> bool:
    if not is_document(filename):
        return False
    if strict and not looks_like_invoice(filename):
        return False
    return True


def ext_of(filename: str) -> str:
    m = DOC_EXT_RE.search(filename or "")
    return m.group(1).lower() if m else "bin"


def slugify(text: str, maxlen: int = 40) -> str:
    slug = re.sub(r"[^\w]+", "-", (text or "").strip().lower()).strip("-")
    return slug[:maxlen].strip("-") or "unknown"


def parse_sender(from_header: str) -> str:
    """Pull a slug-safe sender out of a From header ('Acme <billing@acme.com>')."""
    m = re.search(r"[\w.\-+]+@[\w.\-]+", from_header or "")
    if m:
        return slugify(m.group(0).split("@")[0])
    return slugify(from_header)


def header_value(message: dict, name: str) -> str:
    headers = (message.get("payload") or {}).get("headers") or []
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def internal_date_str(message: dict) -> str:
    ms = message.get("internalDate")
    if not ms:
        return datetime.now(timezone.utc).strftime("%Y%m%d")
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y%m%d")


def strip_ext(filename: str) -> str:
    return DOC_EXT_RE.sub("", filename or "")


def make_filename(date_str: str, sender: str, attachment_name: str, ext: str) -> str:
    """`{YYYYMMDD}_{sender}_{attachment-stem}.{ext}`.

    Refines D4 (which used the subject slug): a single email can carry several
    attachments that share one subject — keying the name on the attachment's
    own filename keeps each distinct instead of silently overwriting."""
    return f"{date_str}_{sender}_{slugify(strip_ext(attachment_name))}.{ext}"


def unique_path(dest_dir, name: str) -> Path:
    """Return a non-colliding path in dest_dir, appending _1/_2/... if needed
    (guards against two different emails producing the same name)."""
    base = Path(dest_dir).expanduser() / name
    if not base.exists():
        return base
    stem, suffix = base.stem, base.suffix
    n = 1
    while True:
        cand = base.with_name(f"{stem}_{n}{suffix}")
        if not cand.exists():
            return cand
        n += 1


def iter_attachments(payload: dict):
    """Walk a Gmail payload tree, yielding (filename, attachmentId, size)."""
    if not payload:
        return
    body = payload.get("body") or {}
    if payload.get("filename") and body.get("attachmentId"):
        yield payload["filename"], body["attachmentId"], body.get("size", 0)
    for part in payload.get("parts") or []:
        yield from iter_attachments(part)


# --- checkpoint (.seen.json) --------------------------------------------

def load_seen(seen_path: str) -> set:
    p = Path(seen_path)
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text()))
    except (json.JSONDecodeError, ValueError):
        logger.warning("seen file %s corrupt, starting fresh", seen_path)
        return set()


def save_seen(seen_path: str, seen: set) -> None:
    p = Path(seen_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(sorted(seen)))
    tmp.replace(p)  # atomic — a crash mid-write never corrupts the checkpoint


# --- rate-limit backoff --------------------------------------------------

def _status_of(exc: Exception):
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    if status is not None:
        try:
            return int(status)
        except (TypeError, ValueError):
            return None
    return None


def _retry_after(exc: Exception):
    resp = getattr(exc, "resp", None)
    if resp is None:
        return None
    getter = getattr(resp, "get", None)
    if callable(getter):
        val = getter("retry-after") or getter("Retry-After")
        if val:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None
    return None


def is_retryable(exc: Exception) -> bool:
    status = _status_of(exc)
    return status in (429, 500, 502, 503, 504)


def with_retry(call, *, sleeper=time.sleep, max_retries: int = MAX_RETRIES):
    """Run `call()`, retrying transient Gmail errors (429/5xx) with exponential
    backoff. Honours a Retry-After header when Gmail sends one. Re-raises any
    non-retryable error, and re-raises the last error after exhausting retries."""
    attempt = 0
    while True:
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 — classify then re-raise
            if not is_retryable(exc) or attempt >= max_retries:
                raise
            delay = _retry_after(exc)
            if delay is None:
                delay = min(BACKOFF_BASE * (2 ** attempt), BACKOFF_CAP)
            logger.warning("transient Gmail error (%s), backing off %.1fs (retry %d/%d)",
                           _status_of(exc), delay, attempt + 1, max_retries)
            sleeper(delay)
            attempt += 1


# --- Gmail calls ---------------------------------------------------------

def list_candidate_ids(service, query: str, *, sleeper=time.sleep):
    """Page through messages.list for `query`, returning ids oldest->newest.

    Gmail returns newest-first; we collect all pages then reverse, so the
    checkpoint advances in chronological order (D2)."""
    ids = []
    page_token = None
    while True:
        req = service.users().messages().list(
            userId=USER_ID, q=query, maxResults=500, pageToken=page_token,
        )
        resp = with_retry(req.execute, sleeper=sleeper)
        ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    ids.reverse()
    return ids


def get_message_meta(service, msg_id: str, *, sleeper=time.sleep) -> dict:
    req = service.users().messages().get(
        userId=USER_ID, id=msg_id, format="full",
    )
    return with_retry(req.execute, sleeper=sleeper)


def fetch_attachment_bytes(service, msg_id: str, att_id: str, *, sleeper=time.sleep) -> bytes:
    req = service.users().messages().attachments().get(
        userId=USER_ID, messageId=msg_id, id=att_id,
    )
    resp = with_retry(req.execute, sleeper=sleeper)
    data = resp.get("data", "")
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


# --- main flow -----------------------------------------------------------

def process_message(service, msg_id, *, dest_dir, strict, dry_run, sleeper, stats):
    msg = get_message_meta(service, msg_id, sleeper=sleeper)
    subject = header_value(msg, "Subject") or "(no subject)"
    sender = parse_sender(header_value(msg, "From"))
    date_str = internal_date_str(msg)

    for filename, att_id, _size in iter_attachments(msg.get("payload") or {}):
        if not should_download(filename, strict=strict):
            stats["skipped_non_invoice"] += 1
            continue
        out_name = make_filename(date_str, sender, filename, ext_of(filename))
        if dry_run:
            logger.info("[dry-run] would save %s  (%s / %s)", out_name, subject, filename)
            stats["would_download"] += 1
            continue
        data = fetch_attachment_bytes(service, msg_id, att_id, sleeper=sleeper)
        out_path = unique_path(dest_dir, out_name)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(data)
        logger.info("saved %s (%d bytes)", out_path.name, len(data))
        stats["downloaded"] += 1


def run(service, *, query=DEFAULT_QUERY, dest_dir=DEFAULT_DIR, seen_path=None,
        strict=False, dry_run=False, sleeper=time.sleep,
        batch_size=BATCH_SIZE, throttle=THROTTLE_SECONDS):
    """Search -> batch -> throttle -> dedup -> download. Returns a summary dict."""
    dest_dir = os.path.expanduser(dest_dir)
    if seen_path is None:
        seen_path = os.path.join(dest_dir, ".seen.json")
    seen = load_seen(seen_path)
    stats = {"candidates": 0, "downloaded": 0, "would_download": 0,
             "skipped_seen": 0, "skipped_non_invoice": 0, "batches": 0}

    ids = list_candidate_ids(service, query, sleeper=sleeper)
    stats["candidates"] = len(ids)
    logger.info("found %d candidate message(s) for query: %s", len(ids), query)

    for start in range(0, len(ids), batch_size):
        batch = ids[start:start + batch_size]
        for msg_id in batch:
            if msg_id in seen:
                stats["skipped_seen"] += 1
                continue
            process_message(service, msg_id, dest_dir=dest_dir, strict=strict,
                            dry_run=dry_run, sleeper=sleeper, stats=stats)
            seen.add(msg_id)
        stats["batches"] += 1
        if not dry_run:
            save_seen(seen_path, seen)  # checkpoint every batch -> crash-safe
        if start + batch_size < len(ids):
            sleeper(throttle)  # throttle between batches, not after the last

    logger.info("done: %s", stats)
    return stats


# --- auth / wiring -------------------------------------------------------

def load_env_file(env_path: str = ".env") -> None:
    p = Path(env_path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def build_gmail_service(account: str = DEFAULT_ACCOUNT):
    """Build an authenticated Gmail service from the refresh token + client creds.
    Imported lazily so the module (and its tests) load without the google libs."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_file = Path("tokens") / f"{account}.json"
    if not token_file.exists():
        raise SystemExit(f"no token for account '{account}' at {token_file} — "
                         f"run the OAuth flow first")
    refresh_token = json.loads(token_file.read_text())["refresh_token"]
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SystemExit("GOOGLE_OAUTH_CLIENT_ID / _SECRET missing from environment/.env")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri=TOKEN_URI,
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def incremental_query(base_query: str, state_path: str) -> str:
    """Weekly-cron window (D7): first run scans 90d, later runs 7d."""
    p = Path(state_path)
    window = "newer_than:90d"
    if p.exists():
        try:
            json.loads(p.read_text())  # presence + validity => not first run
            window = "newer_than:7d"
        except (json.JSONDecodeError, ValueError):
            pass
    return f"{base_query} {window}"


def write_cron_state(state_path: str) -> None:
    p = Path(state_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"last_run": datetime.now(timezone.utc).isoformat()}))


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Gmail invoice auto-downloader (Engine A)")
    ap.add_argument("--dir", default=DEFAULT_DIR, help=f"save dir (default {DEFAULT_DIR})")
    ap.add_argument("--account", default=DEFAULT_ACCOUNT, help="token account id (tokens/<id>.json)")
    ap.add_argument("--query", default=DEFAULT_QUERY, help="Gmail search query")
    ap.add_argument("--before", help="only messages before YYYY/MM/DD (time-split boundary, D2)")
    ap.add_argument("--after", help="only messages after YYYY/MM/DD")
    ap.add_argument("--incremental", action="store_true",
                    help="weekly-cron window: 90d first run, 7d after (D7)")
    ap.add_argument("--strict", action="store_true",
                    help="require an invoice token in the attachment filename too (D3)")
    ap.add_argument("--dry-run", action="store_true", help="log candidates, download nothing")
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    ap.add_argument("--throttle", type=float, default=THROTTLE_SECONDS)
    return ap


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_arg_parser().parse_args(argv)
    load_env_file()

    dest_dir = os.path.expanduser(args.dir)
    query = args.query
    if args.before:
        query += f" before:{args.before}"
    if args.after:
        query += f" after:{args.after}"

    state_path = os.path.join(dest_dir, ".cron-state.json")
    if args.incremental:
        query = incremental_query(query, state_path)

    service = build_gmail_service(args.account)
    stats = run(service, query=query, dest_dir=dest_dir, strict=args.strict,
                dry_run=args.dry_run, batch_size=args.batch_size, throttle=args.throttle)

    if args.incremental and not args.dry_run:
        write_cron_state(state_path)

    print(f"\nSummary: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
