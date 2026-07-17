# MCP patches — Engine B (`multi-email-mcp` invoice download)

Engine B extends the `multi-email-mcp` server (installed globally, **outside this
repo**) so the aureon agent can download email attachments via chat. Because the
server lives in `~/.npm-global/lib/node_modules/multi-email-mcp/`, the changes
can't be committed as normal source — they're captured here as patches.

## What the patches do

`gmail-api.js.patch`
- `listAttachments`: adds `attachmentId` to each attachment object (upstream
  drops it, so nothing downstream could fetch the bytes).
- `downloadAttachment(account, messageId, attachmentId, filename, destDir)`: new —
  fetches the attachment bytes, base64url-decodes, sanitizes the filename,
  expands a leading `~`, and writes to `destDir`. Returns `{saved, size, ...}`.
- `api()`: adds 429/5xx exponential backoff honouring `Retry-After` (the server
  had **no** rate-limit handling) — hardens every Gmail call, not just downloads.

`server.js.patch`
- Registers the `download_attachment` MCP tool (surfaces as
  `mcp_gmail_download_attachment` through aureon's `MCPManager`).

## Apply

```bash
./mcp-patches/apply.sh        # patches the globally-installed module in place
```

Idempotent-ish: it skips a file whose patch is already applied. A `.bak` is
written next to each target the first time.

## Verify

```bash
node tests/mcp_gmail_download.test.mjs   # deterministic: 429 backoff + write, no network
python live_test_gmail_download.py       # live: real Gmail -> real invoice PDF on disk
```
