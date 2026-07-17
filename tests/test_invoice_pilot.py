"""Engine A tests — no network. A hand-built fake Gmail service records calls
and returns programmed responses, so we can assert on batching, throttle,
429 backoff+resume, base64 writes, dedup, and the non-invoice skip path."""
import base64

import httplib2
import pytest
from googleapiclient.errors import HttpError

import invoice_pilot as ip


# --- fake Gmail service --------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _msg(msg_id, subject="Invoice 42", sender="Acme <billing@acme.com>",
         internal_ms="1700000000000", attachments=(("rechnung.pdf", "att1"),)):
    parts = [{"filename": fn, "body": {"attachmentId": aid, "size": 10}} for fn, aid in attachments]
    return {
        "id": msg_id,
        "internalDate": internal_ms,
        "payload": {
            "headers": [{"name": "Subject", "value": subject},
                        {"name": "From", "value": sender}],
            "parts": parts,
        },
    }


class _Req:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class FakeGmail:
    """Chainable stand-in for the googleapiclient Gmail Resource."""

    def __init__(self, *, pages, messages, attachments, fail_once_on=None):
        self._pages = list(pages)          # list of list.execute() responses
        self._messages = messages          # id -> message dict
        self._attachments = attachments    # (msg_id, att_id) -> raw bytes
        self._fail_once_on = set(fail_once_on or ())  # att_ids that 429 once
        self._failed = set()
        self.calls = {"list": 0, "get": 0, "att": 0}
        self.list_queries = []

    # service.users().messages().<op>()
    def users(self):
        return self

    def messages(self):
        return self

    def list(self, userId, q, maxResults, pageToken):
        self.list_queries.append(q)

        def _do():
            self.calls["list"] += 1
            idx = 0 if pageToken is None else int(pageToken)
            return self._pages[idx]
        return _Req(_do)

    def get(self, userId, id, format):
        def _do():
            self.calls["get"] += 1
            return self._messages[id]
        return _Req(_do)

    def _att_get(self, userId, messageId, id):
        def _do():
            self.calls["att"] += 1
            if id in self._fail_once_on and id not in self._failed:
                self._failed.add(id)
                resp = httplib2.Response({"status": 429})
                raise HttpError(resp, b"rate limit")
            return {"data": _b64(self._attachments[(messageId, id)]), "size": 10}
        return _Req(_do)


# attachments().get() and messages().get() collide by name; disambiguate by
# giving the fake an attachments-mode flag via a tiny wrapper.
class FakeAttachments:
    def __init__(self, parent):
        self._p = parent

    def get(self, userId, messageId, id):
        return self._p._att_get(userId, messageId, id)


def _wire(fake):
    fake.attachments = lambda: FakeAttachments(fake)
    return fake


# --- heuristic units -----------------------------------------------------

def test_is_document():
    assert ip.is_document("rechnung.pdf")
    assert ip.is_document("scan.PNG")
    assert ip.is_document("photo.jpeg")
    assert not ip.is_document("logo.gif")
    assert not ip.is_document("")


def test_should_download_strict_gate():
    # Default (non-strict) now REQUIRES an invoice token in the email context
    # (subject/snippet/body) — not just any document attachment.
    assert not ip.should_download("document.pdf")                       # no context -> skip
    assert ip.should_download("document.pdf", subject="Monthly Invoice")  # subject token
    assert ip.should_download("document.pdf", body="your rechnung is attached")  # body token
    # Strict additionally demands the token in the filename itself.
    assert ip.should_download("invoice_123.pdf", strict=True)
    assert not ip.should_download("document.pdf", strict=True)          # no filename token


def test_is_invoice_context_body_snippet():
    # Invoices with a generic subject are still caught via snippet/body (D3 layer 3).
    assert ip.is_invoice_context("Your monthly statement", snippet="find your Rechnung inside")
    assert ip.is_invoice_context("Statement", body="tax invoice attached")
    assert not ip.is_invoice_context("Hello", snippet="nice chat", body="thanks!")


def test_make_filename_uses_attachment_name():
    name = ip.make_filename("20260115", "billing-acme", "Rechnung_03.04.2023_400.pdf", "pdf")
    assert name == "20260115_billing-acme_rechnung_03-04-2023_400.pdf"


def test_unique_path_avoids_collision(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    p = ip.unique_path(str(tmp_path), "a.pdf")
    assert p.name == "a_1.pdf"


def test_multi_attachment_email_no_overwrite(tmp_path):
    # One email, two doc attachments: "Rechnung.pdf" (invoice) + "Retoure.pdf"
    # (a return slip — no invoice token). Tightened detection downloads only the
    # invoice, keying each saved file on its own attachment name (no overwrite).
    msg = {"1": _msg("1", subject="Order 5",
                     attachments=(("Rechnung.pdf", "a1"), ("Retoure.pdf", "a2")))}
    fake = _wire(FakeGmail(pages=[{"messages": [{"id": "1"}]}], messages=msg,
                           attachments={("1", "a1"): b"INV", ("1", "a2"): b"RET"}))
    ip.run(fake, query="q", dest_dir=str(tmp_path), sleeper=lambda _: None)
    pdfs = sorted(p.name for p in tmp_path.glob("*.pdf"))
    assert pdfs == ["20231114_billing_rechnung.pdf"]  # only the invoice, not Retoure
    assert next(tmp_path.glob("*rechnung*.pdf")).read_bytes() == b"INV"


def test_parse_sender():
    assert ip.parse_sender("Acme Corp <billing@acme.com>") == "billing"
    assert ip.parse_sender("noreply@stripe.com") == "noreply"


# --- checkpoint ----------------------------------------------------------

def test_seen_roundtrip_atomic(tmp_path):
    p = tmp_path / "sub" / ".seen.json"
    ip.save_seen(str(p), {"a", "b"})
    assert ip.load_seen(str(p)) == {"a", "b"}
    assert not p.with_suffix(".json.tmp").exists()  # temp cleaned up


def test_load_seen_corrupt(tmp_path):
    p = tmp_path / ".seen.json"
    p.write_text("{not json")
    assert ip.load_seen(str(p)) == set()


# --- backoff -------------------------------------------------------------

def test_with_retry_backs_off_then_succeeds():
    slept = []
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise HttpError(httplib2.Response({"status": 429}), b"")
        return "ok"

    assert ip.with_retry(flaky, sleeper=slept.append) == "ok"
    assert calls["n"] == 2
    assert slept == [1.0]  # BACKOFF_BASE * 2**0


def test_with_retry_honours_retry_after():
    slept = []

    def flaky():
        raise HttpError(httplib2.Response({"status": 503, "retry-after": "7"}), b"")

    with pytest.raises(HttpError):
        ip.with_retry(flaky, sleeper=slept.append, max_retries=1)
    assert slept == [7.0]  # honoured the header, not exp backoff


def test_with_retry_reraises_non_retryable():
    def boom():
        raise HttpError(httplib2.Response({"status": 404}), b"")

    with pytest.raises(HttpError):
        ip.with_retry(boom, sleeper=lambda _: None)


# --- list ordering -------------------------------------------------------

def test_list_candidate_ids_oldest_first_paged():
    fake = _wire(FakeGmail(
        pages=[{"messages": [{"id": "3"}, {"id": "2"}], "nextPageToken": "1"},
               {"messages": [{"id": "1"}]}],
        messages={}, attachments={},
    ))
    ids = ip.list_candidate_ids(fake, "q", sleeper=lambda _: None)
    assert ids == ["1", "2", "3"]  # reversed newest-first -> oldest-first
    assert fake.calls["list"] == 2


# --- full run ------------------------------------------------------------

def _run_fixture(tmp_path, **over):
    msgs = {
        "1": _msg("1", subject="Invoice 1", attachments=(("rechnung.pdf", "a1"),)),
        "2": _msg("2", subject="Rechnung 2", attachments=(("logo.gif", "a2"),)),  # non-doc
        "3": _msg("3", subject="Facture 3", attachments=(("invoice3.pdf", "a3"),)),
    }
    atts = {("1", "a1"): b"PDF-ONE", ("3", "a3"): b"PDF-THREE"}
    fake = _wire(FakeGmail(
        pages=[{"messages": [{"id": "3"}, {"id": "2"}, {"id": "1"}]}],
        messages=msgs, attachments=atts, **over,
    ))
    return fake


def test_run_downloads_writes_bytes_and_skips_non_invoice(tmp_path):
    fake = _run_fixture(tmp_path)
    stats = ip.run(fake, query="subject:invoice", dest_dir=str(tmp_path),
                   sleeper=lambda _: None, batch_size=2)

    files = sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".pdf")
    assert len(files) == 2
    # base64 round-trips to the real bytes (filename keyed on attachment "rechnung.pdf")
    one = next(tmp_path.glob("*rechnung*.pdf"))
    assert one.read_bytes() == b"PDF-ONE"
    assert stats["downloaded"] == 2
    assert stats["skipped_non_invoice"] == 1  # logo.gif
    assert fake.list_queries == ["subject:invoice"]


def test_run_throttles_between_batches(tmp_path):
    fake = _run_fixture(tmp_path)
    slept = []
    ip.run(fake, query="q", dest_dir=str(tmp_path), sleeper=slept.append, batch_size=2)
    # 3 ids, batch_size 2 -> 2 batches -> exactly one inter-batch throttle sleep
    assert slept.count(ip.THROTTLE_SECONDS) == 1


def test_run_dedup_skips_seen(tmp_path):
    seen_path = tmp_path / ".seen.json"
    ip.save_seen(str(seen_path), {"1", "2", "3"})
    fake = _run_fixture(tmp_path)
    stats = ip.run(fake, query="q", dest_dir=str(tmp_path),
                   seen_path=str(seen_path), sleeper=lambda _: None)
    assert stats["downloaded"] == 0
    assert stats["skipped_seen"] == 3
    assert fake.calls["get"] == 0  # never even fetched the messages


def test_run_429_on_attachment_recovers_and_resumes(tmp_path):
    fake = _run_fixture(tmp_path, fail_once_on={"a1"})
    slept = []
    stats = ip.run(fake, query="q", dest_dir=str(tmp_path), sleeper=slept.append, batch_size=50)
    # a1 429s once then succeeds -> still 2 downloads, backoff sleep recorded
    assert stats["downloaded"] == 2
    assert 1.0 in slept  # backoff fired
    assert next(tmp_path.glob("*rechnung*.pdf")).read_bytes() == b"PDF-ONE"


def test_run_dry_run_writes_nothing(tmp_path):
    fake = _run_fixture(tmp_path)
    stats = ip.run(fake, query="q", dest_dir=str(tmp_path),
                   dry_run=True, sleeper=lambda _: None)
    assert stats["would_download"] == 2
    assert stats["downloaded"] == 0
    assert not list(tmp_path.glob("*.pdf"))
    assert not (tmp_path / ".seen.json").exists()  # dry-run never checkpoints
    assert fake.calls["att"] == 0  # never fetched bytes


# --- incremental window --------------------------------------------------

def test_incremental_query_first_run_90d(tmp_path):
    state = tmp_path / ".cron-state.json"
    assert ip.incremental_query("base", str(state)) == "base newer_than:90d"


def test_incremental_query_later_run_7d(tmp_path):
    state = tmp_path / ".cron-state.json"
    ip.write_cron_state(str(state))
    assert ip.incremental_query("base", str(state)) == "base newer_than:7d"
