# aureon-agent — Invoice Auto-Downloader (Mental Model + How It Works)

> Companion doc to `aureon-agent metal model.md` and `aureon-agent gmail mcp.md`. Explains the interview prototype: a prototype AI-agent / automated workflow that searches an inbox, recognizes invoices, downloads them, and saves to a folder. Three engines, one OAuth base. Rate-limit-safe. All live-verified against a real inbox.

---

## Mental Model (the shape)

```
.env (GOOGLE_OAUTH_CLIENT_ID / _SECRET)  +  tokens/vishal.json (refresh_token)
        │
        ├─ Engine A: invoice_pilot.py ──────────google-api-python-client──> Gmail API direct
        ├─ Engine B: MCP patch downloadAttachment ──aureon agent drives──> chat (Telegram/Discord)
        └─ Engine C: scheduler (recurrence)
              └─ aureon cron invoice-weekly (LLM drives MCP tools per turn, Telegram summary)
```

**One OAuth base, three consumers.** The hard part (Gmail OAuth dance) was paid once, earlier. All three engines reuse the same `refresh_token` + client creds. None stores the mailbox password — OAuth 2.0 only.

**Why three pieces?** The interview task said "AI-agents **bzw.** automated workflows" (i.e. OR). Engine A = the standalone workflow script (deterministic, for backfill/dry-run). Engine B = the agent-driven path (MCP tools, chat). Engine C = the agent-native recurrence (`invoice-weekly` cron, Telegram summary). The script + agent cover both phrasings; recurrence stays fully agent-native.

---

## The gap we found (why Engine B needed code)

`multi-email-mcp` (the Gmail MCP server) can **search + recognize** invoices but **cannot download them**:
- `read_message` returned attachment *metadata* (`filename`, `contentType`, `size`) but **dropped `attachmentId`**.
- No tool fetched attachment **bytes**. Gmail attachment bytes = `GET /gmail/v1/users/me/messages/{id}/attachments/{attachmentId}` → `{data: base64}`.
- The `download` call existed ONLY in the rejected IMAP provider (plaintext). The OAuth/gmail-api provider could SEE attachments but not SAVE them.

So: search + recognize = free via MCP. **Download = the only real build.** Engine A avoids the gap (talks to Gmail API directly). Engine B patches the gap (adds the tool).

---

## Engine A — `invoice_pilot.py` (standalone workflow)

Self-contained script. No agent, no MCP. Talks to Gmail REST API directly via the OAuth refresh token.

**Flow:**
```
1. load .env (client_id/secret) + tokens/vishal.json (refresh_token)
2. creds = Credentials(refresh_token, client_id, client_secret, token_uri)
3. gmail = build("gmail","v1", credentials=creds)
4. query = "subject:(invoice OR rechnung OR facture) has:attachment"
5. PAGE messages.list(q=query) oldest->newest (reverse Gmail's newest-first)
6. for each batch (50):
     for id in batch (max 5 parallel):
       msg = messages.get(id, format=full)
       for part with filename+attachmentId:
         if is_document(filename) AND invoice_context(subject/snippet/body):
           att = messages.attachments.get(id, attId) -> base64 decode -> write file
     append ids to .seen.json; sleep(6)
7. print summary
```

**Save:** `~/dev-shared/docs/invoices/` (env `INVOICE_DIR`). Filename `{YYYYMMDD}_{sender}_{attachment-stem}.{ext}`. Collision guard `_1/_2`.

**Dedup:** shared `.seen.json` keyed by message `id`. Both engines write it → no double-download across the 50/50 split.

**CLI:** `python invoice_pilot.py [--dry-run] [--dir DIR] [--before DATE] [--incremental] [--strict]`

---

## Engine B — MCP patch `downloadAttachment` (agent-driven)

Extends `multi-email-mcp` (npm global, outside repo — captured as `mcp-patches/*.patch` + `apply.sh`).

**Patch:**
- `readMessage`: add `attachmentId` to each attachment object (was dropped).
- `downloadAttachment(account, messageId, attachmentId, destDir)`: fetch bytes, base64url-decode, sanitize filename, write file, return `{saved, size}`.
- `api()` helper: add 429/5xx exponential backoff honoring `Retry-After` (server had NONE — hardens every Gmail call).
- `server.js`: register tool `download_attachment` → surfaces as `mcp_gmail_download_attachment`.

**Agent path:**
```
Telegram: "download my recent invoices"
  -> aureon context -> plan
  -> mcp_gmail_search_mail(query)
  -> mcp_gmail_read_message(id)   [now exposes attachmentId]
  -> mcp_gmail_download_attachment(id, attId, ~/dev-shared/docs/invoices)
  -> file on disk
```
Discovered automatically by aureon's `MCPManager` after the server is patched. No `cli.py` change needed.

---

## Engine C — scheduler (recurrence)

**aureon cron (`invoice-weekly`, registered via `scripts/seed-invoice-cron.sh`):**
- `aureon-agent cron create "0 9 * * 1" --tz Europe/Berlin --name invoice-weekly`.
- The cron prompt drives the Engine B MCP tools **as an agent turn** (LLM chains search→read→download), then delivers a **Telegram summary**.
- Live-proven: `minimax-m2.5:cloud` chained 4 rounds, saved a real 75KB `%PDF`.

This is the agent-native recurrence path — it reuses the MCP tools, surfaces in chat/Telegram, and fits aureon's workflow. (An earlier systemd-timer variant was dropped: it bypassed the agent and duplicated the same work outside the runtime.)

---

## Rate-limit defense (the centerpiece — user's explicit caveat)

Gmail cap: **6000 quota units/min/user**, ~50 concurrent max, 429 on breach. `list`=5u, `get`=5u, `attachments.get`=5u.

```
├─ batch 50 msgs, sleep(6) between  → ~5000 u/min (under 6000 cap)
├─ 429 → honor Retry-After; else exp backoff 1s→2s→4s…cap 30s, max 5 retries, RESUME (not restart)
├─ max 5 parallel gets (well under 50 concurrent)
├─ .seen.json checkpoint every batch → crash-safe resume
└─ search-first query (has:attachment + subject tokens) → ~20× fewer calls than scanning 6500
```

**Backfill math:** ~6500 emails, ~300 invoice candidates → ~300 gets + ~300 att = ~3000u total, spread over throttled batches → **zero 429 risk**. The throttle is belt-and-suspenders.

---

## Invoice detection (3 layers — tightened today)

```
layer 1: Gmail query        subject:(invoice OR rechnung OR facture) has:attachment
layer 2: filename type gate /\.(pdf|png|jpe?g)$/i
layer 3: token in subject OR snippet OR body   ← added today
```
- **Default:** invoice token anywhere (filename OR subject/snippet/body).
- **`--strict`:** token must be in the attachment **filename** (drops casual photos like `IMG_1234.jpg` from a "Rechnung" subject email).
- No LLM. Deterministic, cheap, reproducible. Catches generic-subject invoices ("Your monthly statement") via the body/snippet layer.

---

## Backfill + cron window

```
6500 emails → split by TIME boundary (not raw count; IDs ≠ time order)
  ├─ oldest → midpoint: Engine A (script)
  └─ midpoint → newest:  Engine B (agent)   [or vice-versa]
  both write the SAME .seen.json → no overlap double-download

cron recurrence:
  run 1 = newer_than:90d   (catch-up window)
  run ≥2 = newer_than:7d   (weekly delta; .cron-state.json tracks last_run)
  → flat 7d cost after backfill
```

---

## Files

| File | Role |
|---|---|
| `invoice_pilot.py` | Engine A — standalone downloader (433 LoC) |
| `requirements-invoice.txt` | Engine A deps (google-auth, google-api-python-client) — separate from `requirements.txt` |
| `tests/test_invoice_pilot.py` | 20 tests: detection, backoff, throttle, dedup, dry-run, incremental |
| `mcp-patches/gmail-api.js.patch` + `server.js.patch` + `apply.sh` | Engine B — staged MCP patch (applied to global npm module) |
| `tests/mcp_gmail_download.test.mjs` | Engine B — 429 backoff + write, no network |
| `live_test_gmail_download.py` | Engine B — live E2E via aureon's MCPManager |
| `scripts/seed-invoice-cron.sh` | Engine C — registers `invoice-weekly` cron job |
| `live_test_invoice_cron.py` | Engine C — live cron verification |
| `tasks/kickoff-invoice-pilot.md` | the plan (v2) |
| `tokens/vishal.json` | OAuth refresh token (gitignored, 600) |
| `.env` | GOOGLE_OAUTH_CLIENT_ID / _SECRET (gitignored, 600) |

---

## Verification (all live, not mocked)

- **Engine A:** `python invoice_pilot.py --dry-run` → 2 real candidates (buyZOXS 86KB, OpenAI 75KB), correct filenames, 0 false-positives, no 429. Real run wrote both PDFs to `~/dev-shared/docs/invoices/`.
- **Engine B:** `live_test_gmail_download.py` → discovered `mcp_gmail_download_attachment`, `read_message` surfaced `attachmentId`, downloaded real 75KB `%PDF` via aureon's MCPManager.
- **Engine C:** `invoice-weekly` cron job active (next run in ~2d). Agent-native recurrence via aureon scheduler.
- **Tests:** 97 pytest pass (77 existing + 20 invoice). ruff clean. CI green.

---

## Interview framing (what to say)

- "OAuth 2.0, not app passwords — mailbox password never stored."
- "Invoice recognition = deterministic heuristic (Gmail search + filename + body regex), not an LLM — faster, cheaper, reproducible."
- "Rate-limit engineering: batched (50/batch), throttled (6s), 429 exponential backoff + checkpoint-resume — backfills 6500 emails with zero API errors."
- "Idempotent (`.seen.json`) + dry-run — safe to re-run."
- "Two engines on one OAuth base: standalone script (workflow) + MCP-tool driven by my AI agent (agent) — covers both phrasings of the task."
- "Backfill-then-incremental: weekly cron scans 90d once, then 7d — flat cost."
- "Full source + tests, live-verified against my own inbox."
