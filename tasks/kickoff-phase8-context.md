# Task: Phase 8 — Layered Context Builder (Option B)

**Branch:** `feat/aureon-agent-context-layers` (off `dev`)
**Mode:** Builder
**Complexity:** Low-Medium — `context_builder.py` rewrite + `config.py` additions, no new deps
**Estimated effort:** 1 evening, ~120 LoC + tests
**Risk:** token budget math, priority-trim ordering, doctrine-file detection (workspace symlinks)

---

## What this is

The agent's "brain" (its persistent context) is currently **broken + too lean**. `context_builder.py` only loads `SOUL.md` + `IDENTITY.md` at boot. Per `tasks/todo.md` line 23 the intended spec was "SOUL + IDENTITY + skills menu + note:* + time" — but even that is missing `WORKFLOW.md`, `MEMORY.md`, `USER.md`.

**Captain's mental model:** workspace files ARE the agent's context brain. They should be present every session, not JIT-fetched.

**Decision (2026-07-16, Captain's call):** **Option B — Layered context.**
- **Always-on brain (boot, every turn):** SOUL + IDENTITY + WORKFLOW + MEMORY + USER — the permanent identity/preference layer
- **JIT (existing, unchanged):** skill bodies on invoke, `tasks/todo.md` on planning, `DEVLOG.md`/`lessons.md` on debug

This satisfies "brain always present" without unbounded token bloat (only the small doctrine set is permanent; operational files stay JIT).

**Rejected:**
- Option A (full `*.md` load every turn): blows Ollama cloud quota on every message, unbounded growth, context pollution
- Option C (manifest + JIT read): what the agent described — Captain explicitly does NOT want JIT for the brain

---

## Reference docs (read before designing)

1. `context_builder.py` (current, 56 lines) — only loads SOUL + IDENTITY, has `TOKEN_BUDGET=2000`, naive trim
2. `aureon_agent/config.py` — `AureonConfig` dataclass, `from_env()`, `from_file()`, `validate()`
3. `tasks/todo.md` line 23 — intended context spec (doctrine-aware)
4. `tasks/DEVLOG.md` — architecture context
5. `agent_runtime.py:9,50` — `build_system_prompt()` called once per `run()`, result cached for the turn
6. `.openclaw/workspace/` — actual doctrine files (SOUL.md, IDENTITY.md, WORKFLOW.md, MEMORY.md, USER.md, MENTAL-MODEL-TEMPLATE.md)

---

## Decisions confirmed with user (do NOT re-derive)

1. **Layered model (Option B):** doctrine brain always-on, operational files JIT. (Captain's call 2026-07-16)
2. **Brain layer files (always):** SOUL, IDENTITY, WORKFLOW, MEMORY, USER — in that priority order
3. **JIT layer files (unchanged):** skill bodies (on invoke via skill_loader), `tasks/todo.md` (on planning), `DEVLOG.md`/`lessons.md` (on debug)
4. **Budget trim:** doctrine sections are PROTECTED — when over budget, cut JIT-first, never doctrine. (current code cuts notes, which is wrong priority)
5. **MENTAL-MODEL-TEMPLATE.md** is a template, NOT a brain file — exclude from auto-load (only load if explicitly referenced)
6. **Token budget:** raise `TOKEN_BUDGET` to 4000 (doctrine layer ~4-5K chars, leaves room for JIT without trim in normal use)
7. **Skills menu:** keep existing "## Available Skills" section (names + descriptions only) — this is JIT-adjacent, fine as-is
8. **Memory notes:** keep existing SQLite `memory.get_notes()` injection — this is the JIT user-knowledge layer, works

---

## Sub-tasks

### Sub-task 1: Doctrine brain loader (`context_builder.py`, ~60 LoC)

**What:**
- New `_load_brain(workspace_dir)` — reads SOUL, IDENTITY, WORKFLOW, MEMORY, USER in priority order
- Each file wrapped in a labeled section: `## Soul`, `## Identity`, `## Workflow`, `## Memory`, `## User`
- Missing files → skip (don't error). Partial brain OK.
- Returns ordered list of section strings

**Acceptance criteria:**
- `build_system_prompt()` output contains SOUL content
- Contains IDENTITY content
- Contains WORKFLOW content (currently MISSING — this is the bug fix)
- Contains MEMORY content (currently MISSING)
- Contains USER content (currently MISSING)
- Missing file (e.g. no USER.md) → no crash, other sections present

### Sub-task 2: Priority-aware budget trim (`context_builder.py`, ~30 LoC)

**What:**
- New `TOKEN_BUDGET = 4000` (was 2000)
- Trim logic: if over budget, drop JIT sections FIRST (skills menu, memory notes, time), then trim doctrine LAST (protected)
- Doctrine never dropped unless absolutely over budget after JIT removed
- Log WARN with which sections were trimmed

**Acceptance criteria:**
- Under budget: all sections present
- Over budget: JIT dropped first, doctrine retained
- Doctrine-only over budget (huge SOUL): trimmed with WARN, no crash

### Sub-task 3: Config flag (`aureon_agent/config.py`, ~20 LoC)

**What:**
- Add `context_brain_files: list[str]` to `AureonConfig` dataclass (default `["SOUL.md", "IDENTITY.md", "WORKFLOW.md", "MEMORY.md", "USER.md"]`)
- Add `context_token_budget: int` (default 4000)
- `from_env()` reads `AUREON_CONTEXT_BRAIN_FILES` (comma-sep), `AUREON_CONTEXT_TOKEN_BUDGET`
- `redact()` skips these (no secrets)
- `validate()` accepts empty list (JIT-only mode)

**Acceptance criteria:**
- Default config has 5 brain files
- `AUREON_CONTEXT_BRAIN_FILES="SOUL.md,IDENTITY.md"` overrides
- `AUREON_CONTEXT_TOKEN_BUDGET=8000` overrides
- Empty list → JIT-only mode, no crash

### Sub-task 4: Tests + doctor (`tests/test_context_builder.py` + `doctor.py`, ~50 LoC)

**What:**
- `tests/test_context_builder.py`:
  - brain loads all 5 files when present
  - missing file handled gracefully
  - priority trim protects doctrine
  - config override works
- `doctor.py`: `check_context_brain()` — verifies brain files exist (WARN if missing, not fail), reports token estimate
- `tests/test_config.py`: brain_files + token_budget round-trip

**Acceptance criteria:**
- All new tests pass
- Existing 37+ tests still pass (context_builder change is additive)
- `aureon-agent doctor` reports brain file status
- `pytest tests/` green

---

## Out of scope (v1 — explicitly do NOT do)

- Full `*.md` workspace load every turn (Option A — rejected)
- Manifest + JIT read_file for brain (Option C — rejected)
- Skill body pre-loading (stays JIT)
- `tasks/todo.md` / `DEVLOG.md` / `lessons.md` auto-load (stay JIT)
- MENTAL-MODEL-TEMPLATE.md auto-load (template only)
- Context compression / summarization (separate — Phase 6 session compaction exists)
- Per-user brain profiles (single Captain v1)

---

## Full spec reference

**Captain's mental model:** workspace files = agent's context brain, should be present every session.

**Architectural decisions:**
- Brain layer = identity + preferences (SOUL/IDENTITY/WORKFLOW/MEMORY/USER)
- JIT layer = operational state (skills, todo, devlog, lessons)
- Trim priority: JIT → doctrine (doctrine protected)
- Budget 4000 chars (~1K tokens) — doctrine set fits comfortably

**File-by-file plan:**

| File | Action | Lines |
|---|---|---|
| `context_builder.py` | Rewrite (`_load_brain`, priority trim, config-driven) | ~90 (was 56) |
| `aureon_agent/config.py` | Modify (add brain_files + token_budget) | +20 |
| `aureon_agent/doctor.py` | Modify (add `check_context_brain`) | +20 |
| `tests/test_context_builder.py` | New | ~80 |
| `tests/test_config.py` | Modify (brain config round-trip) | +15 |
| `tasks/todo.md` | Modify (add Phase 8 entry) | +15 |
| `tasks/DEVLOG.md` | Modify (Phase 8 closeout) | +20 |

---

## Acceptance criteria (whole task)

- [x] `build_system_prompt()` loads SOUL + IDENTITY + WORKFLOW + MEMORY + USER every turn
- [x] Missing brain file → graceful skip, no crash
- [x] Over-budget trim drops JIT first, doctrine protected
- [x] `AUREON_CONTEXT_BRAIN_FILES` + `AUREON_CONTEXT_TOKEN_BUDGET` env overrides work
- [x] Skills menu (names only) still injected
- [x] Memory notes (SQLite) still injected
- [x] `doctor` reports brain file status
- [x] All tests pass (37+ existing + new)
- [x] No new dependencies
- [x] Bot live under systemd, Telegram round-trip shows brain present (agent references USER prefs without being asked)
