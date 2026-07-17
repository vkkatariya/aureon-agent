# Task: Invoice Auto-Downloader Prototype (job interview task)

**Branch:** `feat/invoice-pilot` (off `dev`)
**Mode:** Builder
**Complexity:** Medium
**Effort:** ~4-5h

---

## 1. Interview task (verbatim, German)

> Vor dem Gespräch haben wir außerdem eine kleine Aufgabe für dich:
> Erstelle einen einfachen Prototypen eines AI-Agents bzw. automatisierten Workflows,
> der ein E-Mail-Postfach durchsucht, Rechnungen erkennt, diese automatisch
> herunterlädt und in einem festgelegten Ordner speichert.
> Du kannst dafür die Tools deiner Wahl verwenden.

**Translation:** build a simple prototype of an AI agent / automated workflow that (1) searches an inbox, (2) recognizes invoices, (3) auto-downloads them, (4) saves to a defined folder. Tools of choice.

**Our leverage:** Gmail OAuth already wired (`multi-email-mcp`, token in `tokens/vishal.json`, client creds in `.env`). ~6500 emails in the inbox.

---

## 2. Audit — HAVE vs MISSING (verified this session)

### HAVE
- `multi-email-mcp` (OAuth `gmail.readonly`), 4 tools: `mcp_gmail_search_mail(account, query, limit)` (full Gmail syntax), `mcp_gmail_read_message(account, id)` → `{subject, from, date, body, attachments:[{filename, contentType, size}]}`, `mcp_gmail_list_recent`, `mcp_gmail_list_accounts`.
- OAuth `refresh_token` in `tokens/vishal.json`; `GOOGLE_OAUTH_CLIENT_ID/SECRET` in `.env` (600).
- `google-auth-library` installed (npm dep).

### MISSING (the gap)
`read_message` returns attachment **metadata only** — internal `attachmentId` (`payload.body.attachmentId`) is **dropped** from tool output. **No tool fetches attachment bytes.** Gmail bytes = `GET /gmail/v1/users/me/messages/{id}/attachments/{attachmentId}` → `{data: base64}`. The `download` call exists only in the rejected IMAP provider. So search+recognize work via MCP; **download needs new code** (standalone script OR MCP patch).

### RATE LIMIT (the real risk — user caveat)
- Gmail cap: **6000 quota units/min/user**, ~50 concurrent max, 429 on breach.
- `messages.list` = 5u, `messages.get` = 5u, `attachments.get` = 5u.
- Naive backfill of 6500 = 429 storm. **Must throttle + backoff + batch + checkpoint.**
- `multi-email-mcp` has **NO 429 handling** (confirmed). The standalone script MUST own this.

---

## 3. Decisions (confirmed with user)

- **D1 — Two engines, one foundation:**
  - **Engine A (Python script `invoice_pilot.py`):** standalone, uses OAuth refresh token + client creds directly via `google-api-python-client`. Self-contained, no agent dependency. Covers "automated workflow".
  - **Engine B (aureon-agent + MCP patch):** extend `multi-email-mcp` with `download_attachment` tool; agent drives search→read→download via chat. Covers "AI agent".
- **D2 — Split 6500 by TIME boundary (not raw count):** find email #3250 by date = midpoint. Script = oldest→midpoint. Agent = midpoint→newest. Both walk **oldest→newest**. (Date boundary deterministic; raw ID order ≠ time order.)
- **D3 — Invoice detection = heuristic, NO LLM:**
  - Search: `subject:(invoice OR rechnung OR facture) has:attachment` (+ optional `newer_than` for cron).
  - Filter: attachment `filename` matches `/\.(pdf|png|jpe?g)$/i` AND `/rechnung|invoice|factur|账单/i`.
- **D4 — Save dir:** `~/dev-shared/docs/invoices/` (env-overridable `INVOICE_DIR`). Filename `{YYYYMMDD}_{sender}_{subject_slug}.{ext}`.
- **D5 — Dedup:** BOTH engines write the SAME `~/dev-shared/docs/invoices/.seen.json` keyed by message `id`. Boundary overlap → no double-download. Makes the 50/50 split safe.
- **D6 — Safety:** `gmail.readonly` (no delete/move). `--dry-run` (log only). Idempotent via `.seen.json`.
- **D7 — Cron (aureon scheduler, reuse Phase 9):** job `invoice-weekly`, weekly. Run 1 = `newer_than:90d`. Run ≥2 = `newer_than:7d`. Window from `~/dev-shared/docs/invoices/.cron-state.json` (`last_run`). Cost flat after backfill.
- **D8 — No secrets in repo:** token + creds from existing `.env`/`tokens/` (gitignored).

---

## 4. Rate-limit defense (centerpiece — both engines)

Gmail: 6000 u/min, 429 at ~50 concurrent.

| Mechanism | Spec |
|---|---|
| Batch size | 50 messages/batch |
| Cost/batch | ~500u (50 × (get 5u + att 5u)) |
| Throttle | `sleep(6s)` between batches → ~5000u/min (under 6000) |
| 429 backoff | honor `Retry-After`; else exp 1s→2s→4s… cap 30s, then resume |
| Concurrency | max 5 parallel `get` (well under 50) |
| Checkpoint | `.seen.json` written every batch → crash-safe resume |
| Search-first | `subject:(invoice OR rechnung) has:attachment` → only candidates fetched (~20× fewer calls than scanning all 6500) |
| Retry | transient network errors retried 3× with backoff |

**Backfill math:** ~6500 emails, ~300 candidates (has:attachment+invoice) → ~300 gets + ~300 att = 3000u total, spread over batches with 6s sleeps → **zero 429 risk**. The throttle is belt-and-suspenders for the full-scan case.

---

## 5. Deliverable A — `invoice_pilot.py` (Engine A)

Deps: `google-auth`, `google-api-python-client` → new `requirements-invoice.txt` (NOT main `requirements.txt`).

**Flow:**
```
1. load .env (client_id/secret) + tokens/vishal.json (refresh_token)
2. creds = google.oauth2.credentials.Credentials(refresh_token, client_id, client_secret, token_uri)
3. gmail = build("gmail","v1",credentials=creds)
4. query = "subject:(invoice OR rechnung OR facture) has:attachment"
5. PAGE through messages.list(q=query) oldest→newest using pageToken, until midpoint reached
6. for each batch (50):
     for id in batch (max 5 parallel get):
       msg = messages.get(id, format=METADATA, metadataHeaders=[Subject,From,Date])
       for part where filename + attachmentId:
         if heuristic(filename) and ext in (pdf,png,jpg):
           att = messages.attachments.get(id, attId) → base64 decode
           write INVOICE_DIR/{date}_{sender}_{slug}.{ext}
     append ids to .seen.json; time.sleep(6)
7. print summary
```
**CLI:** `python invoice_pilot.py [--dry-run] [--dir ~/dev-shared/docs/invoices] [--until <midpoint-date>] [--query "..."]`
**Tests:** `tests/test_invoice_pilot.py` — `googleapiclient` `HttpMock`, assert: query built, batch throttle called, 429 triggers backoff+resume, base64 written, dedup skip on re-run, non-invoice skipped. No network.

---

## 6. Deliverable B — MCP patch + agent (Engine B)

**B1. Patch `gmail-api.js`:**
- `readMessage`: add `attachmentId: payload.body.attachmentId` to each attachment object.
- Add `downloadAttachment(account, messageId, attachmentId, destDir)`:
  ```js
  const client = getClient(account);
  const att = await api(client, `/messages/${encodeURIComponent(messageId)}/attachments/${encodeURIComponent(attachmentId)}`);
  const buf = Buffer.from(att.data.replace(/-/g,"+").replace(/_/g,"/"), "base64");
  const safe = filename.replace(/[^\w.\-]/g, "_");
  fs.mkdirSync(destDir, { recursive: true });
  fs.writeFileSync(path.join(destDir, safe), buf);
  return { saved: path.join(destDir, safe), size: buf.length };
  ```
- `server.js`: register `download_attachment` tool `{account, messageId, attachmentId, destDir}`.
- **Also add 429 backoff to `api()` helper** (the user concern): on 429, respect `Retry-After` or exp backoff, retry up to 5×. This hardens the server for the agent's usage too.

**B2. Agent discovery:** restart bot → `mcp_gmail_download_attachment` auto-discovered (no cli.py change). `aureon-agent mcp list` confirms.

**B3. Agent demo (midpoint→newest):** Telegram "download invoices from <midpoint> to now to ~/dev-shared/docs/invoices" → agent: `search_mail` → `read_message` (gets attachmentId) → `download_attachment`. Writes same `.seen.json`.

**B4. Tests:** `tests/test_mcp_gmail_download.py` — mock `api()` returns base64, assert file written to tempdir + correct name + 429 retry path.

---

## 7. Deliverable C — Cron `invoice-weekly` (aureon scheduler)

- Reuse Phase 9 cron (`aureon_agent/cron.py`). Add job: schedule `0 9 * * 1` (Mon 09:00), prompt runs `invoice_pilot.py` with window logic:
  - read `.cron-state.json` `last_run`.
  - if absent → `newer_than:90d`; else → `newer_than:7d`.
  - after run → write `last_run = now`.
- Idempotent via `.seen.json`. Flat 7d cost after first run.

---

## 8. Out of scope (v1)
LLM classification, vendor subfolders, email delete/archive, multi-account, webhook/daemon (cron covers recurrence).

---

## 9. Verification gate (L-081 — live, not mocked)
- **A:** `python invoice_pilot.py --dry-run` lists REAL candidate invoices. Real run → valid PDFs in `~/dev-shared/docs/invoices/`. `pytest tests/test_invoice_pilot.py` green. Confirm throttle: no 429 in logs.
- **B:** restart bot → `mcp list` shows `download_attachment` → live agent turn downloads 1 REAL invoice → file on disk. Confirm `tokens/vishal.json` intact (patch didn't break auth). Force a 429 in test → backoff fires.
- **C:** trigger `invoice-weekly` manually → run 1 scans 90d; flip state; run 2 scans 7d.
- All hit REAL Gmail before "done".

---

## 10. Files touched
- NEW `invoice_pilot.py`, `requirements-invoice.txt`, `tests/test_invoice_pilot.py`
- PATCH `~/.npm-global/lib/node_modules/multi-email-mcp/src/providers/gmail-api.js` (attachmentId + downloadAttachment + 429 backoff) + `server.js` (register tool)
- NEW `tests/test_mcp_gmail_download.py`
- NEW cron job `invoice-weekly` (aureon `cron.py` / config)
- REWRITE `tasks/kickoff-invoice-pilot.md` (this file)
- aureon `cli.py`: no change (tools auto-discovered)

---

## 11. Interview framing
- "OAuth 2.0, not app passwords — mailbox password never stored."
- "Invoice recognition = deterministic heuristic (Gmail search + filename regex), not an LLM — faster/cheaper/reproducible."
- "**Rate-limit engineering**: batched (50/batch), throttled (6s), 429 exponential backoff + checkpoint-resume — backfills 6500 emails with zero API errors."
- "Idempotent (.seen.json) + dry-run — safe to re-run."
- "Two engines on one OAuth base: standalone script (workflow) + MCP-tool driven by my AI agent (agent) — covers both phrasings of the task."
- "Backfill-then-incremental: weekly cron scans 90d once, then 7d — flat cost."
- "Full source + tests, live-verified against my own inbox."
