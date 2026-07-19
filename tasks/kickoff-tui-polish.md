# Kickoff: polished TUI chrome (lighter than Claude Code / Hermes, Rich-only)

**Context:** Captain wants aureon-agent's interactive TUI (`aureon_agent/repl.py`) to level up its **UI/UX** to match the polish of **Claude Code** and **Hermes Agent** CLIs — but stay **lighter** (no heavy deps; Rich-only chrome, keep `prompt_toolkit` for input only, dep-free where possible).

**Reference surfaces (from screenshots):**
- **Claude Code:** orange banner (`Claude Code v2.1.87`), welcome `Welcome back <name>`, identity line (`Sonnet 4.6 · Claude Pro · <org>`), CWD, two-column box (left = identity, right = Tips + Recent activity), feature announcement line (`/voice to enable`), `> ` prompt, `? for shortcuts`.
- **Hermes Agent:** pixel-art title `HERMES-AGENT` + version, ASCII caduceus logo, session block (model / profile / CWD / session id), "Available Tools" + "Available Skills" lists, profile summary (`N tools · M skills · /help`), `$ ` prompt with model chip + progress + timer.

**Current state (verified):**
- `repl.py` uses **plain `print()`** — minimal banner: `aureon-agent vX — interactive session` + `session: <id>` + `type /help for commands`.
- `HELP` is a plain multi-line string printed verbatim.
- `prompt_toolkit` is used ONLY for the input line (`PromptSession`), NOT for chrome. Keep it that way.
- `rich` is already a project dependency (used by `cmd_sessions`/`cmd_skills_list`/`cmd_status`). **No new dep needed** — build all chrome with Rich.
- Runtime data available at boot: `build_runtime()` returns `agent` (has model/tool info), `SkillLoader` (skills), `SessionManager`. `tool_registry` count = 57 (8 doctrine + 16 inline + 33 MCP). `__version__` available.

## Design — polished but light

### 1. Rich banner (replace `_print_banner`)
A `rich.panel.Panel` or `rich.console.Console` composed banner:
- Title row: `aureon-agent` (bold) + `v{__version__}` (dim) — single line, clean. No heavy pixel-art (that's Hermes's thing; keep ours text+style, lighter).
- Identity block (left-aligned, like Hermes session block):
  ```
  model      claude-opus-4.6 (or whatever runtime uses)
  profile    Captain (Nous)        # from config
  cwd        ~/dev-shared/...      # os.getcwd()
  session    telegram:723865496    # or tui:tty / handed-off id
  ```
- A one-line **tips / hints** footer like Claude's: `type a message to chat · /handoff <id> to continue a chat · /help for commands`.
- Use `rich` `Table` (single-column, no borders or a subtle box) for the identity block — lighter than Hermes's full ASCII logo, same information density.

### 2. Polished `/help` (replace plain HELP print)
Render `HELP` as a `rich.panel.Panel` or a 2-column `Table` (command | description) instead of a raw string. Mirror Hermes's "Available Tools / Skills" density:
- Add a **capabilities summary** line (like Hermes `30 tools · 70 skills`): `57 tools · 8 doctrine skills · /help`. Pull tool count from `tool_registry` + skill count from `SkillLoader`.
- Keep it optional (only compute if cheap; `SkillLoader.load()` is already fast, used at boot).

### 3. Prompt polish (light touch)
- Keep `prompt_toolkit` input. Optionally show a model chip before the prompt (Hermes style `$ [claude-opus-4.6]`) — but that requires custom `PromptSession` formatting. **Keep minimal:** if `prompt_toolkit` present, set `message="aureon> "` (already). Skip the progress-bar/timer (that's Hermes-specific runtime telemetry; aureon doesn't stream a global timer). Don't over-build.

### 4. Feature announcement line (Claude-style)
After banner, one dim line for the active mode: e.g. `interactive session · MCP tools offline (connect_mcp=False)` — this surfaces the known TUI limitation (PR #23 judgment-call #2) transparently, like Claude's `/voice to enable` notice. Honest + polished.

## Constraints
- **Lighter than Claude/Hermes:** Rich-only chrome, NO pixel-art title, NO ASCII mascot, NO progress-bar/timer telemetry. Information parity, not visual weight.
- **No new deps:** `rich` already present. `prompt_toolkit` stays input-only.
- **Reuse:** `Console`/`Panel`/`Table` from `rich` (already imported in `cmd_*`); `tool_registry` count; `SkillLoader`.
- **Caveman mode** replies still apply (SOUL.md) — banner/help are UI chrome, not agent responses.
- **No secrets** in banner (model/version/cwd/session only).

## Tests
- `tests/test_tui.py` (extend): `run_tui` boot prints a banner containing version + session id (capture stdout via `monkeypatch`/fake `Console` or assert `Console` render). `/help` renders a Panel/Table (assert command list present). Keep light — assert key strings (`aureon-agent`, `session:`, `/handoff`) appear in captured output.

## Verification
- `python -m pytest tests/ -q` green; `ruff` clean.
- `python -m aureon_agent.__main__ tui` → banner shows version, session, cwd, tips; `/help` shows styled command table + capability summary.
- `tui --handoff telegram:723865496` → banner shows the handed-off session id.
- No new dependencies added (`pip check` / requirements unchanged except none).

## Suggested commits
- `feat(tui): Rich banner + polished /help (lighter Claude/Hermes-style chrome)`
- `test(tui): banner + help render assertions`
