"""Engine B live verification — drives the patched multi-email-mcp gmail server
through aureon's own MCPManager (the same path the agent uses at runtime).

Proves end-to-end: tool discovery -> search -> read_message surfaces the new
`attachmentId` -> download_attachment writes a real invoice PDF to disk.

Hits REAL Gmail (readonly). Not a pytest test (live_test_ prefix) and not run
in CI. Run manually:  python live_test_gmail_download.py
"""
import asyncio
import json
import os
import tempfile
from pathlib import Path

from aureon_agent.mcp_client import MCPManager

MCP_BIN = os.path.expanduser("~/.npm-global/lib/node_modules/multi-email-mcp/src/server.js")


def _load_env():
    p = Path(".env")
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _unwrap(raw):
    """MCP call_tool returns a JSON string; gmail tools wrap payload as
    {content:[{text: '<json>'}]} or return the JSON directly depending on layer."""
    data = json.loads(raw)
    if isinstance(data, dict) and "content" in data:
        return json.loads(data["content"][0]["text"])
    return data


async def main():
    _load_env()
    cid = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if not (cid and secret):
        print("missing GOOGLE_OAUTH_CLIENT_ID/_SECRET")
        return

    mgr = MCPManager()
    ok = await mgr.add_server(
        server_name="gmail", command="node", args=[MCP_BIN],
        env={
            "MAIL_ACCOUNTS": "vishal",
            "MAIL_VISHAL_PROVIDER": "gmail-api",
            "MAIL_VISHAL_EMAIL": os.environ.get("EMAIL_ADDRESS") or "vishal@example.com",
            "GOOGLE_OAUTH_CLIENT_ID": cid,
            "GOOGLE_OAUTH_CLIENT_SECRET": secret,
        },
    )
    if not ok:
        print("FAIL: gmail MCP server did not start")
        return

    names = [t["name"] for t in mgr.get_tools()]
    print("tools:", names)
    assert "mcp_gmail_download_attachment" in names, "download_attachment tool not discovered"
    print("PASS: download_attachment tool discovered")

    try:
        # 1. search for a recent invoice
        res = _unwrap(await mgr.call_tool("mcp_gmail_search_mail", {
            "query": "subject:(invoice OR rechnung) has:attachment newer_than:400d",
            "account": "vishal", "limit": 5,
        }))
        hits = res.get("results", res if isinstance(res, list) else [])
        assert hits, "no invoice emails found"
        msg_id = hits[0]["id"]
        print(f"search hit: {hits[0].get('subject')!r} id={msg_id}")

        # 2. read_message must now surface attachmentId
        msg = _unwrap(await mgr.call_tool("mcp_gmail_read_message",
                                          {"id": msg_id, "account": "vishal"}))
        atts = [a for a in msg.get("attachments", [])
                if a.get("attachmentId") and a["filename"].lower().endswith((".pdf", ".png", ".jpg", ".jpeg"))]
        assert atts, "no downloadable attachment with attachmentId (patch not applied?)"
        att = atts[0]
        print(f"PASS: attachmentId surfaced for {att['filename']!r}")

        # 3. download it to a temp dir
        with tempfile.TemporaryDirectory() as d:
            out = _unwrap(await mgr.call_tool("mcp_gmail_download_attachment", {
                "account": "vishal", "messageId": msg_id,
                "attachmentId": att["attachmentId"], "filename": att["filename"],
                "destDir": d,
            }))
            saved = Path(out["saved"])
            assert saved.exists() and saved.stat().st_size > 0, "file not written"
            head = saved.read_bytes()[:4]
            print(f"PASS: downloaded {saved.name} ({out['size']} bytes, magic={head!r})")
    finally:
        try:
            await mgr.disconnect_all()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
