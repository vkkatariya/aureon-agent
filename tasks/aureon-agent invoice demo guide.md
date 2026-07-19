# Interview Demo Guide — aureon-agent Invoice Auto-Downloader

> Purpose: a scripted, copy-paste demo of the invoice prototype for an interview.
> Every command and prompt here is real and was live-verified against a real inbox (~6500 emails, 85 PDFs downloaded).
> Source of truth: `tasks/aureon-agent invoice autodownloader.md`, `tasks/aureon-agent metal model.md`, `tasks/DEVLOG.md`, `tasks/todo.md`.
>
> **One OAuth base, three engines.** Gmail OAuth 2.0 was paid once (refresh token in `tokens/vishal.json`, client creds in `.env`). All three engines reuse it. No mailbox password is ever stored.

---

## 0. Setup (already done — show, don't rebuild)

```bash
# aureon-agent repo
cd ~/dev-shared/projects/aureon-agent

# OAuth secrets (gitignored, chmod 600) — prove no plaintext password
ls -la .env tokens/vishal.json
# .env has GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET
# tokens/vishal.json has the gmail.readonly refresh_token

# Show the 3 MCP servers are wired + healthy
aureon-agent doctor        # → "3 server(s) configured: notion, github, gmail"
```

Talking point: *"OAuth 2.0, not app passwords — the mailbox password is never stored. The refresh token is gitignored and chmod 600."*

---

## 1. Engine A — standalone workflow script (backfill / dry-run)

Deterministic, no agent, no LLM. Talks to Gmail REST API directly via the OAuth refresh token. Best for bulk backfill + safe dry-runs.

### 1a. Dry-run first (safe, shows what it would grab)

```bash
source .venv/bin/activate
python invoice_pilot.py --dry-run
```

Expected: lists real invoice candidates (e.g. `buyZOXS 86KB`, `OpenAI credit note 75KB`) with correct filenames, **0 false-positives, no 429**.

### 1b. Real backfill run

```bash
python invoice_pilot.py
# optional flags:
#   --dir ~/dev-shared/docs/invoices   (default via INVOICE_DIR)
#   --before 2024-01-01                (time-split for parallel backfill)
#   --incremental                      (90d first run → 7d after, via .cron-state.json)
#   --strict                           (invoice token must be in the filename)
```

Saves to `~/dev-shared/docs/invoices/`, filenames `{YYYYMMDD}_{sender}_{attachment-stem}.{ext}`, dedup via shared `.seen.json`, throttled (50/batch, 6s sleep), 429 backoff + checkpoint-resume.

Verify:
```bash
ls -la ~/dev-shared/docs/invoices/ | tail -5
file ~/dev-shared/docs/invoices/*.pdf    # → "PDF document"
```

Talking point: *"Recognition is a deterministic 3-layer heuristic (Gmail search + filename type gate + body/snippet token) — no LLM, so it's fast, cheap, reproducible. Idempotent via `.seen.json`, so re-running is safe."*

---

## 2. Engine B — agent-driven via MCP tools (the "AI agent" path)

The agent drives the patched `multi-email-mcp` server through Telegram. This is the **agent-native** path — same tools a human would use, just automated.

### 2a. Live via Telegram (the headline demo)

Send this to `@aureon_agent_bot`:

```
download my recent invoices from gmail to ~/dev-shared/docs/invoices
```

What happens under the hood (agent ReAct, 4 rounds):
```
mcp_gmail_search_mail(query="subject:(invoice OR rechnung OR facture) has:attachment newer_than:7d")
  → mcp_gmail_read_message(id)          # now exposes attachmentId (patch)
  → mcp_gmail_download_attachment(id, attId, ~/dev-shared/docs/invoices)
  → file on disk + Telegram summary
```

### 2b. Prove the MCP tool exists (the gap we closed)

```bash
# (CLI mcp list is flaky on teardown; trust the running bot's registry)
# The running bot logged at startup:
#   tool registry: 57 tools (skill: 8, inline: 16, mcp: 33)
# gmail server = 5 tools: search_mail, read_message, list_recent, list_accounts, download_attachment
```

The `download_attachment` tool **did not exist** in the upstream server — we added it (`mcp-patches/gmail-api.js.patch` + `server.js.patch`, applied to the global npm module, captured in-repo + `apply.sh`). Upstream `read_message` also dropped `attachmentId`; the patch restores it.

Talking point: *"The MCP server could search and recognize invoices but couldn't download them — it dropped `attachmentId` and had no byte-fetch tool. I patched it: added `download_attachment` + surfaced `attachmentId`, plus 429 backoff on every Gmail call. The agent now drives search→read→download as a normal tool chain."*

### 2c. Out-of-process live proof (no bot restart needed)

```bash
python live_test_gmail_download.py
# → discovers mcp_gmail_download_attachment, downloads a real 75KB %PDF via aureon's MCPManager
```

---

## 3. Engine C — agent-native recurrence (the cron)

The weekly scheduler. Agent-driven, fits aureon's workflow, delivers a Telegram summary. **This is the only retained scheduler** — the standalone systemd timer variant was dropped (it bypassed the agent and duplicated work outside the runtime).

### 3a. Register the weekly job (one-time)

```bash
aureon-agent cron create "0 9 * * 1" --tz Europe/Berlin --name invoice-weekly \
  --deliver telegram --timeout-sec 600 \
  --prompt "Find invoice emails from the last 7 days. Use the gmail tools in order: mcp_gmail_search_mail, then mcp_gmail_read_message for each, then mcp_gmail_download_attachment for each invoice PDF/PNG/JPG. Save to ~/dev-shared/docs/invoices. Never delete or modify any email. Reply with a one-line summary: 'saved N: <filenames>'."
```

### 3b. Show it's scheduled

```bash
aureon-agent cron list          # → invoice-weekly, next run Mon 09:00 Europe/Berlin
aureon-agent cron runs invoice-weekly   # run history (name resolves, not just ID)
```

### 3c. Fire it on demand (demo the recurrence now)

```bash
aureon-agent cron run invoice-weekly     # queues → scheduler tick → agent turn → Telegram summary
```

Expected: agent runs the prompt as an isolated `cron:<id>:<ts>` session, downloads, and posts a Telegram summary like `saved 2: rechnung.pdf, creditnote.pdf`.

Talking point: *"Recurrence is fully agent-native — it's literally the same agent turn you'd trigger from Telegram, just auto-fired weekly and summarized back to me. The cron job only runs while the bot is alive, which is fine for a personal inbox."*

---

## 4. Operator surface (slash commands — no SSH needed)

From Telegram, self-serve health:

```
/status     → rich 5-section block (service, runtime/model, tokens, session, cron+mcp)
/sessions   → list chat sessions
/doctor     → health checks (incl. all 3 MCP servers)
/cron       → list cron jobs
/mcp        → list MCP servers + tools
/logs       → recent bot logs
/version    → agent version
/help       → command list
```

All output is wrapped in a MarkdownV2 code block so Rich tables render aligned in chat (they break otherwise).

---

## 5. Rate-limit engineering (the centerpiece)

Gmail cap: **6000 quota units/min/user**, ~50 concurrent max, 429 on breach.

```
├─ batch 50 msgs, sleep(6) between  → ~5000 u/min (under 6000 cap)
├─ 429 → honor Retry-After; else exp backoff 1s→2s→4s…cap 30s, max 5 retries, RESUME (not restart)
├─ max 5 parallel gets (well under 50 concurrent)
├─ .seen.json checkpoint every batch → crash-safe resume
└─ search-first query (has:attachment + subject tokens) → ~20× fewer calls than scanning 6500
```

Backfill math: ~6500 emails → ~300 invoice candidates → ~3000u total, throttled → **zero 429 risk**.

Talking point: *"Rate-limit engineering is the real work: batched, throttled, exponential backoff with checkpoint-resume. It backfills 6500 emails with zero API errors — and it's idempotent, so re-running is free."*

---

## 6. Interview narrative (the 60-second pitch)

> "I built an invoice auto-downloader as an AI-agent slash automated-workflow prototype. One Gmail OAuth base, three engines:
> 1. A **standalone script** for deterministic bulk backfill and dry-runs — no LLM, rate-limit-safe.
> 2. An **agent-driven path** where my AI agent chains Gmail MCP tools (search → read → download) through Telegram — I had to patch the MCP server because it could see attachments but couldn't save them.
> 3. An **agent-native weekly cron** that auto-fires the same agent turn and summarizes back to me on Telegram.
>
> Recognition is a deterministic heuristic, not an LLM. Everything is idempotent, dry-runnable, and live-verified against my own inbox — 85 invoices downloaded, zero API errors. Full source and tests on GitHub."

---

## Appendix — file map

| File | Role |
|---|---|
| `invoice_pilot.py` | Engine A — standalone downloader |
| `requirements-invoice.txt` | Engine A deps (separate from agent deps) |
| `tests/test_invoice_pilot.py` | Engine A tests (detection, backoff, throttle, dedup, dry-run) |
| `mcp-patches/*.patch` + `apply.sh` | Engine B — staged MCP patch (applied to global npm) |
| `tests/mcp_gmail_download.test.mjs` | Engine B — 429 backoff + write |
| `live_test_gmail_download.py` | Engine B — live E2E via MCPManager |
| `scripts/seed-invoice-cron.sh` | Engine C — registers `invoice-weekly` |
| `live_test_invoice_cron.py` | Engine C — live cron verification |
| `tokens/vishal.json` | OAuth refresh token (gitignored, 600) |
| `.env` | `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` (gitignored, 600) |

## Verification status (all live, not mocked)
- Engine A: `--dry-run` → 2 real candidates; real run wrote both PDFs; no 429.
- Engine B: `live_test_gmail_download.py` → real 75KB `%PDF` via patched MCP.
- Engine C: `invoice-weekly` active; `cron run` downloaded + summarized to Telegram.
- Tests: 111 pytest pass (incl. 20 invoice + 11 status/slash); ruff clean; CI green.
- Result: **85 valid PDFs** in `~/dev-shared/docs/invoices/`.
