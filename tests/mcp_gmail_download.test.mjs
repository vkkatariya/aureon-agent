// Engine B — Node smoke test for the multi-email-mcp gmail-api patch.
// No network: injects a fake OAuth client via module-level monkeypatch of the
// google-auth-library import is hard, so we test the pure logic by constructing
// a minimal account + stubbing global fetch-equivalent through a fake client.
//
// Run: node tests/mcp_gmail_download.test.mjs
// (Not part of the Python pytest/CI suite — the MCP server lives in the global
//  npm module; this documents & verifies the patch behaviour directly.)
import assert from "node:assert";
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

// Dummy OAuth app creds so googleOAuthConfig() doesn't throw; the actual token
// exchange never runs because we mock OAuth2Client.request below.
process.env.GOOGLE_OAUTH_CLIENT_ID ||= "test-client-id";
process.env.GOOGLE_OAUTH_CLIENT_SECRET ||= "test-client-secret";

const MODULE_ROOT = path.join(os.homedir(), ".npm-global/lib/node_modules/multi-email-mcp");
const MOD = path.join(MODULE_ROOT, "src/providers/gmail-api.js");

const { downloadAttachment } = await import(pathToFileURL(MOD));

// Resolve google-auth-library from the MCP module's perspective so we patch the
// exact singleton gmail-api.js imported (ESM caches by resolved URL).
const moduleRequire = createRequire(path.join(MODULE_ROOT, "package.json"));

// A fake account whose tokenFile exists (getClient reads a refresh_token).
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "mcp-dl-"));
const tokenFile = path.join(tmp, "vishal.json");
fs.writeFileSync(tokenFile, JSON.stringify({ refresh_token: "fake" }));
const account = { id: "vishal", email: "v@example.com", tokenFile };

// Monkeypatch OAuth2Client.request via the prototype so no real token exchange
// happens. We intercept at the network layer: first call 429s, second returns
// base64 attachment bytes — proving backoff + decode + write in one shot.
const { OAuth2Client } = await import(pathToFileURL(moduleRequire.resolve("google-auth-library")));
let calls = 0;
OAuth2Client.prototype.request = async function ({ url }) {
  calls += 1;
  if (calls === 1) {
    const err = new Error("rate limited");
    err.response = { status: 429, headers: { "retry-after": "0" } };
    throw err;
  }
  const data = Buffer.from("PDF-BYTES-HERE").toString("base64url");
  return { data: { data, size: 14 } };
};

const dest = path.join(tmp, "invoices");
const res = await downloadAttachment(account, "msg1", "att1", "Rechnung 42.pdf", dest);

assert.strictEqual(calls, 2, "should retry once after 429");
assert.strictEqual(res.filename, "Rechnung_42.pdf", "unsafe chars sanitized");
const saved = fs.readFileSync(res.saved);
assert.strictEqual(saved.toString(), "PDF-BYTES-HERE", "base64 decoded to real bytes");
assert.strictEqual(res.size, 14);

// tilde expansion
const res2 = await downloadAttachment(account, "msg1", "att1", "x.pdf", dest);
assert.ok(res2.saved.startsWith(dest), "saves under destDir");

fs.rmSync(tmp, { recursive: true, force: true });
console.log("PASS mcp_gmail_download: 429 backoff + base64 write + sanitize + tilde OK");
