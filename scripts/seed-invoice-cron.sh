#!/usr/bin/env bash
# Engine C (variant 2) — agent-driven weekly invoice sweep via the aureon cron
# scheduler. Registers a cron job whose prompt drives the Engine B MCP tools
# (search_mail -> read_message -> download_attachment) as an agent turn, then
# delivers a summary to Telegram.
#
# This is the "AI agent does recurring work" variant. It runs alongside the
# systemd timer (systemd/aureon-invoice.timer), which is the deterministic
# script-based path. Pick either; they target the same folder.
#
# Idempotent-ish: re-running creates a second job. Check `aureon-agent cron list`
# first. Requires a bot restart afterwards so the running scheduler's MCP
# subprocess loads the patched download_attachment tool.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

read -r -d '' PROMPT <<'EOF' || true
Weekly invoice sweep. Find invoice emails from the last 7 days and download their attachments to a folder.

Use the gmail tools, in order:
1. mcp_gmail_search_mail  account="vishal"  query="subject:(invoice OR rechnung OR facture) has:attachment newer_than:7d"  limit=20
2. For each result, mcp_gmail_read_message  id=<message id>  account="vishal"  — read its attachments[] (each carries an attachmentId).
3. For every attachment whose filename ends in .pdf, .png, .jpg or .jpeg, call
   mcp_gmail_download_attachment  account="vishal"  messageId=<id>  attachmentId=<attachmentId>  filename=<filename>  destDir="~/dev-shared/docs/invoices"
4. Reply with a one-line summary: how many attachments were saved and their filenames. If none, say "no new invoices this week".

Do not delete or modify any email — download only.
EOF

exec aureon-agent cron create "0 9 * * 1" \
  --name "invoice-weekly" \
  --prompt "$PROMPT" \
  --deliver telegram \
  --timeout-sec 600 \
  --tz Europe/Berlin \
  "$@"
