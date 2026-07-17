#!/usr/bin/env bash
# Apply the Engine B patches to the globally-installed multi-email-mcp server.
# Idempotent: skips a file whose patch already applied. Writes a .bak once.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${MULTI_EMAIL_MCP_SRC:-$HOME/.npm-global/lib/node_modules/multi-email-mcp/src}"

apply_one() {
  local target="$1" patch="$2"
  if [ ! -f "$target" ]; then
    echo "SKIP (missing): $target"; return
  fi
  if patch -s -R --dry-run "$target" < "$patch" >/dev/null 2>&1; then
    echo "already applied: $target"; return
  fi
  if ! patch -s --dry-run "$target" < "$patch" >/dev/null 2>&1; then
    echo "ERROR: patch does not apply cleanly to $target" >&2; exit 1
  fi
  [ -f "$target.bak" ] || cp "$target" "$target.bak"
  patch -s "$target" < "$patch"
  node --check "$target" && echo "patched + syntax OK: $target"
}

apply_one "$SRC/providers/gmail-api.js" "$HERE/gmail-api.js.patch"
apply_one "$SRC/server.js"              "$HERE/server.js.patch"
echo "done — restart the aureon bot to load the new tool"
