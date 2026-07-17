# aureon-agent — Gmail MCP (Mental Model + How It Works)

> Companion doc to `aureon-agent metal model.md`. Explains the Gmail MCP integration from first principles: what it is, why OAuth (not plaintext), how a message gets from Google's servers to the agent, and every wall we hit getting it live.

---

## 1. Mental Model

```
┌─────────────────┐     OAuth 2.0 (gmail.readonly)     ┌──────────────────────┐
│  Google Gmail   │ ◄─────────────────────────────────► │  multi-email-mcp     │
│  API (remote)   │   token in tokens/vishal.json       │  (stdio server on    │
└─────────────────┘                                     │   athena, node)      │
                                                          └──────────┬───────────┘
                                                                     │ stdio (JSON-RPC)
                                                                     │ mcp_gmail_* tools
                                                                     ▼
                                                          ┌──────────────────────┐
                                                          │  aureon-agent         │
                                                          │  (MCPManager →         │
                                                          │   ToolRegistry →       │
                                                          │   AgentRuntime)        │
                                                          └──────────────────────┘
```

**The core idea:** aureon-agent does NOT talk to Gmail's HTTP API directly. It spawns a **local stdio MCP server** (`multi-email-mcp`) as a child process. The server speaks JSON-RPC over stdin/stdout. The agent calls **tools** (`mcp_gmail_list_recent`, etc.) — it never sees OAuth tokens, HTTP, or JSON parsing.

**Why OAuth instead of a password:**
- A Gmail **App Password** (what the first attempt used) is a 16-char secret living in plaintext `.env`. Account-scoped, revocable, but still a secret-in-a-file.
- **OAuth 2.0** with `gmail.readonly` scope: the server holds a **refresh token** (cached in `tokens/vishal.json`, gitignored). The mailbox password is never stored anywhere. Token is revocable from Google Account settings in one click. This is strictly safer — Captain's call: *"storing gmail password in plaintext is risky."*

**Token vs Secret distinction (critical):**
- `tokens/vishal.json` = the **OAuth token** (access + refresh). Auto-refreshed. Lives on athena, gitignored.
- `GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_SECRET` = the **OAuth app credentials** (from your Google Cloud project). Needed at runtime to *refresh* the token. These are NOT the mailbox password — they're the app's identity. Stored in aureon-agent's `.env` (chmod 600, gitignored).

---

## 2. The Package

**`oliverkoast/multi-email-mcp@0.1.0`** — local stdio MCP server, MIT, active.
- Supports **Gmail + Outlook** from one connection (we use Gmail only).
- Provider `gmail-api` = OAuth 2.0, scope `https://www.googleapis.com/auth/gmail.readonly`.
- Token cached in `tokens/<account>.json` (gitignored).
- **Rejected alternatives:**
  - `gmail-mcp-imap` (agent's first pick) — IMAP + App Password plaintext. Rejected per Captain.
  - `mcp-server-gmail` — stray install, unused, removed.
  - `GongRzhe/Gmail-MCP-Server` (Captain's suggestion) — **ARCHIVED/read-only since 2026-03**. Dead dep.
  - Google Official Gmail MCP — hosted/Cloud-Run remote endpoint, not stdio-on-athena. Heavier, out of scope.

---

## 3. End-to-End: How a "list my recent emails" turn works

1. **Agent starts** → `cli.py` builds the MCP server list → spawns `node .../multi-email-mcp/src/server.js` as a child process (stdio).
2. **Server boots** → reads env `MAIL_ACCOUNTS=vishal`, `MAIL_VISHAL_PROVIDER=gmail-api`, `MAIL_VISHAL_EMAIL=...`, `GOOGLE_OAUTH_CLIENT_ID/SECRET`. Loads `tokens/vishal.json`. Prints `gmail-multi MCP server ready — accounts: vishal`.
3. **Handshake** → `MCPManager` connects, discovers 4 tools: `mcp_gmail_search_mail`, `mcp_gmail_read_message`, `mcp_gmail_list_recent`, `mcp_gmail_list_accounts`.
4. **User says** "list my recent emails" → `AgentRuntime` (MINIMAX via Ollama) decides to call `mcp_gmail_list_recent` with `{account: vishal, limit: 5}`.
5. **Server calls Gmail API:** `GET /gmail/v1/users/me/messages?maxResults=5` (5 quota units) → then `GET /gmail/v1/users/me/messages/{id}?format=metadata` per message (5u each). Total ≈ 30 quota units.
6. **Gmail returns** real message metadata (subject/from/date/snippet) → server serializes to MCP result → agent gets structured data → LLM summarizes.
7. **Verified output (this session):** Captain's actual GitHub CI-failure notification emails from `vkkatariya/aureon-agent`.

**Tools (read-only, v1 — no `send`):**
| Tool | Gmail API call | Quota cost |
|---|---|---|
| `mcp_gmail_list_recent` | `messages.list` (5u) + N×`messages.get` metadata (5u each) | ~30u @ limit 5 |
| `mcp_gmail_search_mail` | `messages.list?q=` (5u) + gets | ~30u @ limit 5 |
| `mcp_gmail_read_message` | `messages.get?format=full` (5u) | 5u |
| `mcp_gmail_list_accounts` | none (local config) | 0u |

---

## 4. The OAuth Dance (headless athena)

athena is a Linux box with **no browser/display**. Google's OAuth needs a browser to consent. Solution = **SSH port-forward tunnel**:

```
# On Mac (your laptop):
ssh -L 32807:localhost:32807 radxa@athena
# → Mac localhost:32807 now forwards to athena localhost:32807

# On athena (ssh session):
cd ~/.npm-global/lib/node_modules/multi-email-mcp
export MAIL_ACCOUNTS=vishal
export MAIL_VISHAL_PROVIDER=gmail-api
export MAIL_VISHAL_EMAIL=vkkatariya2020@gmail.com
export GOOGLE_OAUTH_CLIENT_ID=***.apps.googleusercontent.com
export GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-***
npm run auth vishal
# → prints consent URL
```

1. Open the URL on your **Mac browser** → sign in as `vkkatariya2020@gmail.com` → grant read-only Gmail.
2. Google redirects to `http://localhost:32807?code=...` → hits **athena** via the SSH tunnel → `auth.js` captures the code, exchanges it for tokens.
3. Token saved to `tokens/vishal.json` on athena (chmod 600).
4. Copy/move token to where the **bot** expects it: `~/dev-shared/projects/aureon-agent/tokens/vishal.json` (the bot reads from its own `tokens/` dir, not the npm pkg dir).

**Google Cloud Console setup (one-time):**
- OAuth consent screen = **External** (not Internal — Internal blocks personal gmail with `Error 403: org_internal`).
- Add `vkkatariya2020@gmail.com` as a **test user** (app in "Testing" mode).
- Authorized redirect URI = `http://localhost:32807` (see Issue #3).

---

## 5. Issues Faced & How We Fixed Them

### Issue #1 — Stray IMAP packages, plaintext secret
- **Symptom:** Agent's first attempt (`feat/aureon-agent-phase7-mcp-servers`) used `gmail-mcp-imap` (App Password in `.env`) + stray `mcp-server-gmail`.
- **Root cause:** Agent picked the easy path; Captain flagged plaintext risk.
- **Fix:** Uninstalled both (`npm uninstall -g gmail-mcp-imap mcp-server-gmail`); removed IMAP env reads from `cli.py`/`doctor.py`. Swapped to OAuth `multi-email-mcp` on branch `feat/aureon-agent-gmail-oauth`.

### Issue #2 — `Error 403: org_internal`
- **Symptom:** Google consent page: "Access blocked: clawdbot can only be used within its organisation."
- **Root cause:** OAuth client was type **Internal** (Workspace-only). Personal gmail ≠ in that org.
- **Fix:** Google Cloud Console → OAuth consent screen → **User type = External**. Added `vkkatariya2020@gmail.com` as test user.

### Issue #3 — `Error: doesn't comply with Google's OAuth 2.0 policy` + "register the redirect URI"
- **Symptom:** After flipping to External, Google rejected the `redirect_uri=http://127.0.0.1:32807`.
- **Root cause:** `auth.js` bound `127.0.0.1:<ephemeral port>`. Google treats `127.0.0.1` as a **web redirect URI** (needs manual registration, and rejects it for public clients). `localhost` is auto-approved as loopback. Also ephemeral port = can't pre-register.
- **Fix:** Patched `src/auth.js` (lines 49-57) to bind a **FIXED port on `localhost`**:
  ```js
  const LOOPBACK_PORT = 32807;
  const server = http.createServer();
  await new Promise((resolve) => server.listen(LOOPBACK_PORT, "localhost", resolve));
  const redirectUri = `http://localhost:${LOOPBACK_PORT}`;
  ```
  Registered `http://localhost:32807` in Google Cloud OAuth client (Authorized redirect URIs).

### Issue #4 — Token never saved (paste-to-chat mistake)
- **Symptom:** First consent attempt: agent printed URL, user pasted the redirect URL (`?code=...`) into chat. Token file never written.
- **Root cause:** The `code` redirects to **localhost** — which on the user's Mac ≠ athena. Browser's redirect hit Mac's localhost (connection refused), code never reached athena's `auth.js`.
- **Fix:** Used **SSH tunnel** (`ssh -L 32807:localhost:32807`) so Mac localhost → athena. Browser redirect lands on athena via tunnel → token saved. Also had to kill a zombie process (pid 4140500) holding port 32807 (`EADDRINUSE`) before re-run.

### Issue #5 — "No Gmail OAuth token cached" on bot start
- **Symptom:** After restart, `mcp list` showed `gmail` with warning: token not found at `~/dev-shared/projects/aureon-agent/tokens/vishal.json`.
- **Root cause:** `npm run auth` wrote the token to the **npm pkg dir** (`~/.npm-global/.../multi-email-mcp/tokens/`), but the bot reads from its **own `tokens/` dir**.
- **Fix:** `cp ~/.npm-global/.../tokens/vishal.json ~/dev-shared/projects/aureon-agent/tokens/vishal.json && chmod 600`. Confirmed gitignored.

### Issue #6 — Client secret missing at runtime
- **Symptom:** Server connected but `list_recent` returned: *"Provider gmail-api needs GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET in .env."*
- **Root cause:** Token alone isn't enough — OAuth refresh needs the app credentials. They existed only in the user's Mac shell env, never on athena.
- **Fix:** Added both `GOOGLE_OAUTH_*` lines to aureon-agent's `.env` (chmod 600, gitignored). Required at runtime for token refresh. **Not the mailbox password.**

### Issue #7 — Broken `live_test_gmail.py`
- **Symptom:** Agent's own live test printed "No Gmail credentials found. Skipping live test."
- **Root cause:** Test checked `os.getenv("EMAIL_ADDRESS")` (IMAP model) — never updated for OAuth. No real API call happened.
- **Fix:** Verified via a direct tool-call harness (`/tmp/gmail_tool2.py`) that calls `mcp_gmail_list_recent` with creds from the project `.env` → returned real emails. The agent's "live test passed" was a skip; our harness proved it live.

### Issue #8 — `mcp list` foreground hang
- **Symptom:** `python -m aureon_agent mcp list` timed out at 60s in foreground.
- **Root cause:** Command spins up all 3 servers + teardown has an anyio cancel-scope warning that delays exit.
- **Fix:** Run in background (`terminal background=true`), poll the log file. Not a real bug — just slow teardown.

---

## 6. Rate Limits (deferred mitigation)

- **Cap:** 6,000 quota units/min per user (project cap 1.2M/min, not the bottleneck). ~50 concurrent requests/mailbox hidden limit → 429.
- **Cost:** `list`=5u, `get`=5u, `send`=100u (v1 read-only, no send). `list_recent(5)`≈30u → ~200 calls/min ceiling.
- **Gap:** `multi-email-mcp` has **NO 429/backoff/retry** (confirmed in `gmail-api.js`).
- **Mitigation (NOT yet implemented):** (1) patch `gmail-api.js` with exponential backoff + `Retry-After`; (2) agent checks Gmail only on cron schedule (every 30m), not every turn; (3) cache last-check timestamp in memory. Only a risk if agent polls Gmail autonomously without a schedule. Session used ~3 calls. Negligible.

---

## 7. Files & Locations

| What | Path |
|---|---|
| MCP server (npm global) | `~/.npm-global/lib/node_modules/multi-email-mcp/` |
| Auth script (patched) | `~/.npm-global/.../multi-email-mcp/src/auth.js` (localhost:32807) |
| Gmail provider | `~/.npm-global/.../multi-email-mcp/src/providers/gmail-api.js` |
| **Token (bot reads this)** | `~/dev-shared/projects/aureon-agent/tokens/vishal.json` (chmod 600, gitignored) |
| OAuth app creds | `~/dev-shared/projects/aureon-agent/.env` (`GOOGLE_OAUTH_CLIENT_ID` + `_SECRET`, chmod 600, gitignored) |
| Server wiring | `aureon_agent/cli.py` (abs path + env map), `aureon_agent/doctor.py` (MCP check) |
| Tests | `tests/test_mcp_gmail.py` (mocked) |

---

## 8. Verification Checklist (done this session)

- [x] `npm run auth vishal` → token saved on athena
- [x] Token copied to aureon-agent `tokens/vishal.json`
- [x] `GOOGLE_OAUTH_*` in `.env`
- [x] `mcp list` → `gmail │ connected │ 4 tools`
- [x] `mcp_gmail_list_recent` → **real Gmail emails** (Captain's GitHub CI notifications)
- [x] 77/77 tests pass; bot active with notion + github + gmail

---

*Session: 2026-07-17. Phase 7.3 Gmail OAuth (Option B). Part of `feat/aureon-agent-gmail-oauth` → merged to `dev` at `0ac5406`.*
