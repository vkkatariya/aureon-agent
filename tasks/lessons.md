# Lessons
> Every mistake or correction gets an entry here.
> Format: Symptom → Root cause → Fix → Prevention rule.

---

## L-001 (2026-07-13): Plan-node work "shipped" but never merged into dev
**Symptom:** Captain reported "Phase 6.5 done, plan-node hard block v2 shipped". Audit found 11/11 tests pass (missing `test_plan_node.py`), `plan_node.py` was 31 lines (v1 soft check, not v2 hard block), doctor had no `check_plan_node()` health check.
**Root cause:** Agent's `feat/aureon-agent-plan-node-hard-block` branch had the work (commit `f671a59`, 96 lines, 6 files including `tests/test_plan_node.py`). But that commit was only on the remote branch, not in dev's history. Either the user said "merged" without actually merging, or the merge happened on a different checkout that wasn't pushed.
**Fix:** Cherry-picked `f671a59` to dev at `ea06f46`. Now dev has the v2 plan-node, 13/13 tests pass, doctor shows "Plan Node OK".
**Prevention:** When a user says "shipped", don't trust the report — `git log --oneline origin/<branch>..dev` to verify. If the branch is ahead of dev, the work isn't in dev. Add to audit checklist.

## L-002 (2026-07-13): Agent's subagent-dispatch work introduced a `NameError` in doctor.py
**Symptom:** `aureon-agent-doctor` crashed with `NameError: name 'shutil' is not defined` at `aureon_agent/doctor.py:68` (in `check_claude_cli`).
**Root cause:** Agent added `check_claude_cli()` that uses `shutil.which("claude")` but didn't add `import shutil` to the imports.
**Fix:** One-line `import shutil` added to `aureon_agent/doctor.py` (commit `740f208`).
**Prevention:** When adding a new function that uses a stdlib module, always check the imports at the top of the file. Add a linter rule (pyflakes/ruff) to catch this. Add to agent verification checklist: "for every new function, check it imports what it uses".

## L-003 (2026-07-13): `tasks/todo.md` Phase 6.5 marked done before plan-node was actually merged
**Symptom:** todo.md (commit `2b15d42`) had Tier 4 sub-tasks checked off, but plan-node wasn't in dev yet.
**Root cause:** todo.md was updated based on the agent's report ("shipped"), not on git verification. Same root cause as L-001.
**Fix:** Cherry-picked `f671a59`, then re-ran the live verification to confirm.
**Prevention:** Update todo.md only after git verification, not based on user/agent reports. The "audit all work in dev" step is mandatory before marking any task done.

## L-004 (2026-07-13): Cherry-pick of consolidation commit lost the session-compaction DEVLOG entry
**Symptom:** After the kickoff consolidation (`57d2f35`), `tasks/DEVLOG.md` was 11988 bytes instead of the expected 17062. The session-compaction agent's DEVLOG entry (added in `e7b99f3`) was gone.
**Root cause:** Cherry-pick onto `dev` (at `bf6a355`) used dev's pre-session-compaction tree as the base, dropping the `e7b99f3` DEVLOG blob. The session-compaction work hadn't been merged into dev's local tree when the cherry-pick happened.
**Fix:** Restored from `git show e7b99f3:tasks/DEVLOG.md` (commit `aa49781`).
**Prevention:** When cherry-picking from a branch, check the parent's tree state. If the source branch has content the target doesn't, the cherry-pick result is incomplete. Alternative: do a rebase, not a cherry-pick, so the parent state is preserved.

## L-005 (2026-07-13): Doctor `shutil.which` regression: `subprocess` import didn't auto-import `shutil`
**Symptom:** Doctor crashed with `NameError: name 'shutil' is not defined` at `aureon_agent/doctor.py:68`.
**Root cause:** The file imported `os, sys, subprocess, httpx, typing` but used `shutil.which()` in `check_claude_cli()`. Python doesn't auto-import stdlib modules — each needs an explicit `import` line.
**Fix:** Added `import shutil` after `import os`.
**Prevention:** Same as L-002. Use `ruff check` in CI to catch undefined names. Or add a `__all__` + explicit imports for any file that uses stdlib.

## L-006 (2026-07-15): Stale `.pyc` caused bot to run old code despite source fix being deployed
**Symptom:** Fixed `agent_runtime.py` cron DB path bug at 00:17:19. Bot restarted at 00:18:08. Bot still returned "No cron jobs configured" (old behavior). Source file had the fix. `python -c "from agent_runtime import AgentRuntime; ..."` in a fresh process returned the correct result.
**Root cause:** Python bytecode caching. `__pycache__/agent_runtime.cpython-312.pyc` was compiled at 00:17:07 from the **pre-fix** source (race condition: the `.pyc` was compiled 2 seconds after the `patch` tool wrote the fix, but from the old version that was in the compiler's memory). When the bot started at 00:18:08, Python compared timestamps: source `00:17:05` vs `.pyc` `00:17:07`. Since `.pyc` was NEWER, Python used the stale `.pyc` without recompiling.
**Fix:** `rm -f __pycache__/agent_runtime.cpython-312.pyc` + restart the bot. Python recompiles fresh from the fixed source.
**Prevention:** After patching a Python file that a long-running process imports, delete the `__pycache__/*.pyc` for that file before restarting. Or: `find . -name '__pycache__' -exec rm -rf {} +` before any deploy. Or: set `PYTHONDONTWRITEBYTECODE=1` in the systemd unit to disable `.pyc` caching entirely (slower startup, but no stale cache issues).

## L-007 (2026-07-15): LLM tool parameter type mismatch causes infinite tool-call loop
**Symptom:** Bot showed "(no response from LLM)" for every message. Journal showed 5 `chat/completions` calls per turn (hitting `MAX_TOOL_ROUNDS=5`) with no text output. LLM was calling `terminal` tool 5 times in a row, never producing a final text response.
**Root cause:** The LLM sent `{"command": "ls -la /path"}` (string) but the tool's JSON schema said `command` is `array of strings`. The tool returned `"Error: Command must be provided as a list, not a single string."`. The LLM retried with the same format, got the same error, retried again, 5 times, never produced text.
**Fix:** `aureon_agent/tools/terminal.py` — accept both string and list. `shlex.split()` the string for safety. `agent_runtime.py` — JSON schema changed to `oneOf: [array, string]` so the LLM sees both as valid.
**Prevention:** Always design tool parameter schemas to be LENIENT on input shape. LLMs don't naturally produce strict array formats — they send strings. Accept string OR array, parse internally. Don't make the LLM learn a format it doesn't naturally produce.

## L-008 (2026-07-15): `subprocess.run` with `shell=False` doesn't expand `~`
**Symptom:** `terminal_tool('ls -la ~/dev-shared/projects/aureon-agent')` returned `ls: cannot access '~/dev-shared/projects/aureon-agent': No such file or directory`.
**Root cause:** `subprocess.run(command, shell=False)` passes args directly to `execve()` which doesn't do shell expansion. `~` is a shell feature, not a filesystem feature.
**Fix:** `aureon_agent/tools/terminal.py` — expand `~` in path-like arguments with `os.path.expanduser()` before passing to `subprocess.run`.
**Prevention:** When using `subprocess.run` with `shell=False` (which is correct for security), manually expand `~` and environment variables (`$HOME`, `$USER`) in path-like arguments. Or: document that the tool only accepts absolute paths.
