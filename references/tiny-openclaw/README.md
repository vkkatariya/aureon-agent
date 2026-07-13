# Tiny-OpenClaw (vendored reference)

Offline copy of [ashishbamania/Tiny-OpenClaw](https://github.com/ashishbamania/Tiny-OpenClaw) for reference while building `aureon-agent`.

## Why vendored

- **Offline-first** — agent can read these without network.
- **Frozen** — pinned to a specific commit so upstream changes don't surprise us mid-build.
- **Easy diff** — compare our port against the reference line-by-line.

## Pin

- **Commit SHA:** see `PINNED_COMMIT.txt`
- **Vendored at:** see `VENDORED_AT.txt`
- **Source:** https://github.com/ashishbamania/Tiny-OpenClaw
- **Substack tutorial:** https://substack.com/home/post/p-193348119 (build walkthrough by the author)

## What's here

| File | LoC | Role (per upstream) |
|---|---|---|
| `main.py` | ~40 | Entry. wires Memory + Sessions + Skills + Agent + Telegram |
| `agent_runtime.py` | ~130 | Anthropic httpx client, ReAct tool loop, MAX_TOOL_ROUNDS=5 |
| `context_builder.py` | ~40 | `load_soul()` + `build_system_prompt(skills, memory)` |
| `telegram_channel.py` | ~90 | python-telegram-bot polling, 4096-char reply split |
| `skill_loader.py` | ~80 | Scans `skills/`, parses SKILL.md frontmatter, importlib loads handler.py |
| `session_manager.py` | ~50 | JSON file CRUD, key=`f"{channel}:{chat_id}"` |
| `memory.py` | ~35 | dict + JSON file (tutorial calls it `memory_store.py` — naming drift) |
| `SOUL.md` | ~20 | Personality + 5 rules |
| `README.md` | — | Upstream README with deps + run instructions |

## What we kept vs. changed in `aureon-agent`

| Upstream choice | Our delta | Why |
|---|---|---|
| Anthropic Messages API | Ollama (OpenAI-compat) + cloud fallback | Local-first, reuse your existing Ollama config |
| Telegram only | Telegram + Discord | Multi-channel from day 1 |
| JSON files (SESSIONS.json, MEMORY.json) | SQLite | Matches your openclaw.sqlite pattern, no corruption on crash |
| `MAX_TOOL_ROUNDS = 5` | Same | Works fine, keep simple |
| ReAct loop with `tool_use` blocks | Same protocol | Standard Anthropic format, Ollama OpenAI-compat supports it |
| Anthropic hardcoded `_call_anthropic` | Pluggable provider | `_call_anthropic` becomes `_call_provider` with provider switch |
| No streaming (callback scaffolded) | Streaming | Telegram `editMessageText` throttled 1/sec |
| No subagent dispatch | Reuse Hermes `delegate_task` | Don't reinvent |
| No plan-node check | Soft warning (v1), hard block (v2) | Per OpenClaw MEMORY.md §"Per-Project AGENTS.md Contract" |
| No doctrine loading | Load SOUL/USER/IDENTITY/WORKFLOW/MEMORY from `~/.openclaw/workspace/` | One source of truth, symlinked |
| Skills: SKILL.md + handler.py | Same format | Reuse your 8 OpenClaw skills as-is |

## How to update the pin (if upstream changes)

```bash
cd ~/dev-shared/projects/aureon-agent/references/tiny-openclaw
NEW_SHA="<new-sha-from-gh-api>"
BASE="https://raw.githubusercontent.com/ashishbamania/Tiny-OpenClaw/${NEW_SHA}"
for f in main.py agent_runtime.py context_builder.py telegram_channel.py skill_loader.py session_manager.py memory.py SOUL.md README.md; do
  curl -sL "${BASE}/${f}" -o "${f}"
done
echo "${NEW_SHA}" > PINNED_COMMIT.txt
date -u -Iseconds > VENDORED_AT.txt
git add -A && git commit -m "chore(references): update tiny-openclaw pin to ${NEW_SHA:0:7}"
```

Only do this if you actually want a reference update. The pin is frozen on purpose.
