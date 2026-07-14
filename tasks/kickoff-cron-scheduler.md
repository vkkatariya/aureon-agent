# Task: Cron scheduler for aureon-agent

**Branch:** `feat/aureon-agent-cron-scheduler` (off `dev`)
**Mode:** Builder
**Complexity:** Medium — new asyncio scheduler + CLI + SQLite tables, but reuses existing agent_runtime + channels
**Estimated effort:** 1 evening, ~450 LoC + tests

---

## What this is

Add a cron scheduler to aureon-agent that runs as an asyncio task inside the bot process. Same architecture as Hermes and OpenClaw: scheduler ticks every 60s, checks for due jobs, spawns isolated agent runs, delivers output to Telegram (or Discord, local, all). Jobs persist in SQLite across restarts.

This enables Captain to schedule recurring tasks (daily health checks, weekly container updates, periodic email checks) and one-shot reminders ("remind me in 20 minutes"). The bot wakes up at the right time, runs the task in an isolated session, and delivers the result to Telegram automatically.

## Reference docs (read before designing)

- **Hermes cron implementation:** `hermes cron --help`, `hermes cron list` (live jobs on athena)
- **OpenClaw cron docs:** `~/.npm-global/lib/node_modules/openclaw/docs/automation/cron-jobs.md` — full spec of schedule types, delivery, run history, isolated sessions, timeout watchdogs
- **OpenClaw heartbeat vs cron:** `~/.npm-global/lib/node_modules/openclaw/docs/automation/cron-vs-heartbeat.md` — when to use each
- **OpenClaw heartbeat docs:** `~/.npm-global/lib/node_modules/openclaw/docs/gateway/heartbeat.md` — the polling-based alternative
- **Existing aureon-agent architecture:** `CLAUDE.md` + `CONTEXT.md` + `tasks/DEVLOG.md` (last 3 entries)
- **Existing agent_runtime:** `agent_runtime.py` — the ReAct loop that cron jobs will call
- **Existing channel router:** `channels/router.py` — the `send_message()` method that cron delivery will use
- **Existing SQLite pattern:** `memory.py`, `session_manager.py`, `compaction/log.py`, `aureon_agent/subagent/log.py` — all use aiosqlite with WAL mode, append-only audit tables

## Decisions confirmed with user (2026-07-14)

### Architecture (matches Hermes + OpenClaw)

- **Scheduler runs inside the bot process** as an asyncio task (NOT a separate process, NOT system cron). Same as Hermes Gateway and OpenClaw Gateway.
- **Jobs persist in SQLite** (`data/cron_jobs.db`) so restarts don't lose schedules. Same as both systems.
- **Isolated sessions:** each cron run gets a fresh `session_id = cron:<job_id>:<timestamp>`. No conversation history from main session. Same as Hermes.
- **Self-contained prompts:** the prompt must be fully self-contained (agent has no context from main session). Same as Hermes.
- **Skills loaded per job:** if `--skills homelab-health` is specified, load only that skill (not all 8). Same as Hermes.
- **Deliver to channel:** output goes to Telegram (or Discord, local, all). Same as Hermes.
- **No streaming:** cron runs don't stream to Telegram (no `on_token` callback). Output is sent as one message after completion. Same as Hermes.
- **One-shot auto-delete:** `--repeat 1` jobs auto-delete after success. Same as OpenClaw `--delete-after-run`.
- **Run history:** `cron_runs` table logs every execution with status, output, duration. Same as both systems.

### Schedule types (matches OpenClaw)

| Type | Example | Description |
|---|---|---|
| `cron` | `0 8 * * *` | 5-field cron expression (minute hour day month weekday) |
| `cron` | `0 */6 * * *` | Every 6 hours |
| `interval` | `30m` | Every 30 minutes |
| `interval` | `2h` | Every 2 hours |
| `interval` | `1d` | Every day |
| `at` | `2026-07-15T09:00:00` | One-shot ISO timestamp (auto-delete after run) |

- **Cron expressions:** parsed by `croniter` library (same as OpenClaw uses `croner`). 5-field Vixie cron. Day-of-month and day-of-week use OR logic (standard Vixie behavior).
- **Intervals:** `Nm` (minutes), `Nh` (hours), `Nd` (days). Simple parsing.
- **One-shot timestamps:** ISO 8601. Without timezone = UTC. With `--tz Europe/Berlin` = local.
- **Top-of-hour staggering:** recurring `cron` expressions at `:00` are auto-staggered by up to 5 minutes to reduce load spikes. Use `--exact` to force precise timing. (Matches OpenClaw.)

### Delivery

- `deliver` field: `telegram` (default), `discord`, `local` (no delivery, just log), `all` (fan out to every connected channel).
- `chat_id` field: which Telegram chat to deliver to. Defaults to `TELEGRAM_ALLOWED_CHATS` (Captain's chat). Per-job override possible.
- Output format: `📋 **<job_name>**\n\n<agent_output>` for Telegram. Plain text for Discord.
- **No delivery for `local`:** job runs, output logged to `cron_runs` table, no message sent. Use for background maintenance tasks.

### Isolation

- Each cron run gets `session_id = cron:<job_id>:<started_at_timestamp>`.
- No conversation history loaded (fresh session, just the prompt as first user message).
- No memory notes loaded (cron sessions are ephemeral).
- Skills loaded per job spec (if `--skills homelab-health`, only `homelab-health` is loaded; if no `--skills`, no skills loaded — bare agent).
- **Same agent_runtime.run()** is called, just with a fresh session and optionally restricted skills.

### Timeout + error handling (matches OpenClaw watchdogs)

- **Default timeout:** 300s (5 min). Configurable per job via `--timeout-sec`.
- **Timeout behavior:** on timeout, abort the agent run, log `status='timeout'` to `cron_runs`, deliver a timeout notification to the channel: `⏰ Job '<name>' timed out after <N>s`.
- **Error behavior:** on exception, log `status='failed'` with error text to `cron_runs`, deliver error notification: `❌ Job '<name>' failed: <error>`.
- **Stalled detection:** if a job hasn't produced any LLM call within 30s of starting, log `status='failed'` with `error='stalled before first model call'`. (Matches OpenClaw's watchdog.)
- **Retry:** no retry in v1. Failed jobs are logged, next run happens on next schedule tick. (v2: `--retry N` for retry count.)

### Persistence + restart behavior

- Jobs in `data/cron_jobs.db` (SQLite, WAL mode).
- On bot restart: scheduler reads all enabled jobs, calculates `next_run_at` for each, resumes scheduling.
- **Overdue jobs on restart:** if a job's `next_run_at` is in the past when the bot starts, reschedule to next future occurrence (don't replay immediately). (Matches OpenClaw: "overdue isolated agent-turn jobs are rescheduled out of the channel-connect window instead of replaying immediately.")
- **One-shot jobs overdue on restart:** if `--at` time has passed, delete the job (it's too late). Log a warning.

### CLI (matches Hermes + OpenClaw ergonomics)

```bash
aureon-agent cron list                              # list all jobs
aureon-agent cron create <schedule> [options]        # create a job
aureon-agent cron pause <job_id>                     # disable a job (keep it)
aureon-agent cron resume <job_id>                    # re-enable a paused job
aureon-agent cron run <job_id>                       # force run on next tick
aureon-agent cron remove <job_id>                    # delete a job
aureon-agent cron runs <job_id>                      # run history for a job
aureon-agent cron status                             # scheduler running? next tick?
```

**`cron create` options:**
- `--name <name>` (required) — human-readable job name
- `--prompt <text>` (required) — self-contained task instruction
- `--skills <name1,name2,...>` (optional) — skills to load (comma-separated)
- `--deliver <telegram|discord|local|all>` (default: telegram)
- `--chat-id <id>` (optional) — Telegram chat to deliver to (default: TELEGRAM_ALLOWED_CHATS)
- `--model <model>` (optional) — model override (default: agent's default model)
- `--timeout-sec <N>` (default: 300) — per-run timeout
- `--repeat <N>` (default: 0 = infinite) — N runs then auto-delete (1 = one-shot)
- `--tz <timezone>` (optional) — timezone for cron expressions (default: UTC)
- `--exact` (flag) — disable top-of-hour staggering
- `--enabled` (flag, default: true) — create as enabled or paused

### Skill loading per job

- If `--skills` is not specified: load NO skills. Bare agent with just the system prompt (SOUL + IDENTITY + WORKFLOW). Tools are still available (terminal, file, web, etc.).
- If `--skills homelab-health`: load only `homelab-health` skill. Other 7 skills are NOT loaded.
- If `--skills homelab-health,notion`: load both.
- Implementation: `SkillLoader` needs a `load_subset(names: list[str])` method that only loads specified skills. Or filter `get_tools()` to only return tools for specified skills.

### Heartbeat vs cron (document in docs/cron.md)

| | Heartbeat (future) | Cron (this task) |
|---|---|---|
| **Trigger** | Polling (every ~30 min) | Exact schedule |
| **Context** | Main session (has history) | Isolated session (fresh) |
| **Use for** | Batch checks (email + calendar in one turn) | Exact timing, one-shot reminders, isolated tasks |
| **Token cost** | Lower (batch) | Higher (fresh session each time) |
| **Isolation** | None | Full |
| **Output** | Goes to main session | Delivered to configured channel |

**Heartbeat is NOT implemented in this task.** This task is cron-only. Heartbeat is a separate future task (Phase 6 or 7). Document the difference in `docs/cron.md` so Captain knows when to use each.

## Read these on session start (in order)

1. `CLAUDE.md` — project context
2. `CONTEXT.md` — stack, infra, decisions
3. `tasks/DEVLOG.md` (last 3 entries) — current world state
4. `tasks/todo.md` — current phase status
5. This file (the kickoff)
6. `~/.npm-global/lib/node_modules/openclaw/docs/automation/cron-jobs.md` — OpenClaw cron spec (the reference implementation)
7. `agent_runtime.py` — the ReAct loop you'll call from cron jobs
8. `channels/router.py` — the `send_message()` method you'll use for delivery
9. `aureon_agent/subagent/log.py` — the SQLite audit log pattern to follow for `cron_runs`

## Your role

You are adding a background scheduler to the bot. The scheduler runs as an asyncio task inside the existing bot process (no new process, no system cron). It reuses the existing `agent_runtime.run()` for execution and `channels/router.py` for delivery. Self-improvement loop: when a cron job fails or behaves unexpectedly, append to `workspace/tasks/lessons.md` (numbered L-NNN).

---

## 6 sub-tasks (in order)

### Sub-task 1: SQLite schema + db init (45 min)

Create `aureon_agent/cron_db.py`:

- [ ] `data/cron_jobs.db` — SQLite, WAL mode (same pattern as `memory.py`, `session_manager.py`, `compaction/log.py`)
- [ ] `cron_jobs` table:
  ```sql
  CREATE TABLE IF NOT EXISTS cron_jobs (
      id TEXT PRIMARY KEY,              -- uuid8 hex
      name TEXT NOT NULL,
      schedule TEXT NOT NULL,          -- cron expr "0 8 * * *" or interval "30m" or ISO "2026-07-15T09:00"
      schedule_type TEXT NOT NULL,     -- 'cron' | 'interval' | 'at'
      prompt TEXT NOT NULL,             -- self-contained task instruction
      skills TEXT DEFAULT '[]',         -- JSON array of skill names
      deliver TEXT DEFAULT 'telegram',  -- 'telegram' | 'discord' | 'local' | 'all'
      chat_id TEXT,                     -- Telegram chat to deliver to (default: TELEGRAM_ALLOWED_CHATS)
      model TEXT,                       -- optional model override
      timeout_sec INTEGER DEFAULT 300,
      repeat INTEGER DEFAULT 0,         -- 0 = infinite, N = N runs then delete
      enabled INTEGER DEFAULT 1,
      tz TEXT DEFAULT 'UTC',
      exact INTEGER DEFAULT 0,          -- disable staggering
      created_at REAL NOT NULL,
      last_run_at REAL,
      next_run_at REAL,
      run_count INTEGER DEFAULT 0
  );
  ```
- [ ] `cron_runs` table (append-only audit log):
  ```sql
  CREATE TABLE IF NOT EXISTS cron_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id TEXT NOT NULL,
      session_id TEXT,                  -- cron:<job_id>:<started_at>
      started_at REAL NOT NULL,
      finished_at REAL,
      status TEXT NOT NULL,             -- 'running' | 'success' | 'failed' | 'timeout'
      output TEXT,                      -- agent response (truncated to 10KB)
      error TEXT,
      duration_sec REAL,
      FOREIGN KEY (job_id) REFERENCES cron_jobs(id)
  );
  CREATE INDEX IF NOT EXISTS idx_cron_runs_job_id ON cron_runs(job_id);
  CREATE INDEX IF NOT EXISTS idx_cron_runs_started_at ON cron_runs(started_at);
  ```
- [ ] `init_db()` async function — creates tables if not exist, sets WAL mode
- [ ] `add_job()`, `get_job()`, `list_jobs()`, `update_job()`, `remove_job()`, `get_due_jobs()` async functions
- [ ] `add_run()`, `finish_run()`, `list_runs()` async functions
- [ ] Test: create job, list jobs, get due jobs, add run, finish run, list runs

### Sub-task 2: Schedule parsing + next-run calculation (45 min)

Create `aureon_agent/cron_schedule.py`:

- [ ] `detect_schedule_type(schedule: str) -> str` — returns `'cron'`, `'interval'`, or `'at'`
  - If contains `T` and (`-` or `:`): `'at'` (ISO timestamp)
  - If matches `^\d+[mhd]$`: `'interval'`
  - Otherwise: `'cron'` (5-field cron expr)
- [ ] `calc_next_run(schedule: str, schedule_type: str, from_time: float, tz: str = 'UTC', exact: bool = False) -> float`
  - `cron`: use `croniter(schedule, from_time, ret_type=float).get_next()`. Apply timezone via `croniter(schedule, from_time, tz=tz)`.
  - `interval`: parse `Nm`/`Nh`/`Nd`, return `from_time + interval_seconds`
  - `at`: parse ISO 8601, return timestamp. If no timezone, assume UTC.
- [ ] **Top-of-hour staggering:** if `schedule_type == 'cron'` and minute field is `0` and `exact=False`, add random 0-300 seconds (0-5 min) to `next_run_at`. Log at INFO: "staggered by Ns".
- [ ] `parse_interval(s: str) -> int` — `"30m" → 1800`, `"2h" → 7200`, `"1d" → 86400`. Raise `ValueError` on invalid format.
- [ ] `parse_iso_timestamp(s: str) -> float` — parse ISO 8601, return Unix timestamp. Raise `ValueError` on invalid.
- [ ] Test: all 3 schedule types, staggering, timezone, invalid inputs

### Sub-task 3: CronScheduler — the asyncio loop + job runner (90 min)

Create `aureon_agent/cron.py`:

- [ ] `class CronScheduler`:
  - `__init__(self, db_path, agent_runtime, channel_router, workspace_dir, default_chat_id)`
  - `async start()` — init db, start `_loop` as asyncio task
  - `async stop()` — cancel `_loop` task, wait for in-flight jobs to finish (best-effort, 30s grace)
  - `async _loop()` — every 60s: call `_tick()`, catch exceptions, log errors
  - `async _tick()` — query `get_due_jobs(now)`, for each: `asyncio.create_task(self._run_job(job))`
  - `async _run_job(job: dict)` — the core runner:
    1. Create `session_id = f"cron:{job['id']}:{int(started)}"`
    2. Insert run row in `cron_runs` with `status='running'`
    3. **Stalled detection:** start a 30s watchdog — if no `chat/completions` call happens within 30s, abort and log `status='failed', error='stalled before first model call'`
    4. Build callbacks: `{'on_token': None, 'on_tool_use': None, 'context': {'router': router, 'session_id': session_id, 'channel_name': 'cron', 'client_id': job['id']}}`
    5. Load skills: if `job['skills']` is non-empty, call `SkillLoader.load_subset(names)`. If empty, use bare agent (no skills, but tools still available).
    6. Build history: `[{'role': 'user', 'content': job['prompt']}]`
    7. Call `agent_runtime.run(history, session_id, callbacks)` with `asyncio.wait_for(timeout=job['timeout_sec'])`
    8. On success: capture output, log `status='success'` to `cron_runs`, deliver to channel
    9. On timeout: log `status='timeout'`, deliver timeout notification
    10. On exception: log `status='failed'` with error, deliver error notification
    11. On stalled: log `status='failed', error='stalled before first model call'`, deliver error
    12. Reschedule or delete (see `_reschedule`)
  - `async _deliver(job: dict, output: str)` — route to the right channel based on `job['deliver']`:
    - `telegram`: `router.send_message(f"telegram:{job['chat_id'] or default_chat_id}", f"📋 **{job['name']}**\n\n{output}")`
    - `discord`: `router.send_message(f"discord:{job['chat_id'] or default_chat_id}", f"📋 **{job['name']}**\n\n{output}")`
    - `local`: no delivery, just log
    - `all`: fan out to all connected channels
  - `async _reschedule(job: dict)` — after a successful run:
    - If `schedule_type == 'at'`: delete the job (one-shot complete)
    - If `repeat > 0` and `run_count >= repeat`: delete the job (repeat count reached)
    - Otherwise: calculate `next_run_at = calc_next_run(...)`, update `last_run_at = now`, `next_run_at = next`, `run_count += 1`
- [ ] Test: mock agent_runtime + router, create a job, run `_tick()`, verify run logged + delivered + rescheduled

### Sub-task 4: SkillLoader subset loading (30 min)

Patch `skill_loader.py`:

- [ ] Add `async def load_subset(self, names: list[str])` — load only skills whose name is in `names`. Skip others.
- [ ] Add `def get_tools_subset(self, names: list[str]) -> list` — return only tools for specified skills.
- [ ] Keep existing `load()` and `get_tools()` unchanged (backward compat).
- [ ] Test: load_subset with 1 name, 2 names, 0 names, invalid name (skip with warning)

### Sub-task 5: CLI subcommands (90 min)

Create `aureon_agent/cron_cli.py` + wire into `aureon_agent/__main__.py`:

- [ ] `aureon-agent cron list` — Rich table: id (8 chars), name, schedule, deliver, next_run (relative: "in 2h 15m"), status (active/paused), last run status
- [ ] `aureon-agent cron create <schedule> [options]` — create a job:
  - `--name` (required)
  - `--prompt` (required)
  - `--skills` (comma-separated, optional)
  - `--deliver` (default: telegram)
  - `--chat-id` (optional, default: TELEGRAM_ALLOWED_CHATS from .env)
  - `--model` (optional)
  - `--timeout-sec` (default: 300)
  - `--repeat` (default: 0 = infinite)
  - `--tz` (default: UTC)
  - `--exact` (flag)
  - `--disabled` (flag — create as paused)
  - Print: "Created job <id>: <name>, next run: <relative_time>"
- [ ] `aureon-agent cron pause <job_id>` — set `enabled=0`
- [ ] `aureon-agent cron resume <job_id>` — set `enabled=1`, recalculate `next_run_at`
- [ ] `aureon-agent cron run <job_id>` — set `next_run_at = now` (force run on next tick)
- [ ] `aureon-agent cron remove <job_id>` — delete from `cron_jobs` (keep `cron_runs` history)
- [ ] `aureon-agent cron runs <job_id>` — Rich table: started_at, status, duration, output (truncated to 80 chars), error
- [ ] `aureon-agent cron status` — scheduler running?, next tick in Ns, jobs due now, last tick at
- [ ] Test: create, list, pause, resume, run, remove, runs, status — all work end-to-end

### Sub-task 6: Wire scheduler into bot startup + doctor + tests + docs (60 min)

- [ ] **`aureon_agent/__main__.py`** — after channels start, before `shutdown.wait()`:
  ```python
  from aureon_agent.cron import CronScheduler
  cron = CronScheduler(
      db_path=os.path.join(DATA_DIR, 'cron_jobs.db'),
      agent_runtime=agent,
      channel_router=router,
      workspace_dir=BASE_DIR,
      default_chat_id=os.environ.get('TELEGRAM_ALLOWED_CHATS', '').split(',')[0],
  )
  await cron.start()
  logger.info("cron scheduler started")
  ```
  On shutdown: `await cron.stop()` before `router.stop_all()`.
- [ ] **`aureon_agent/doctor.py`** — add `check_cron_scheduler()`:
  - Verify `data/cron_jobs.db` is readable
  - Count enabled jobs
  - Check last tick was within 90s (scheduler is alive)
  - Check for stuck jobs (status='running' for > 10 min — should be impossible with timeout, but catch bugs)
- [ ] **`requirements.txt`** — add `croniter>=1.4`
- [ ] **`pyproject.toml`** — add `aureon_agent.cron` + `aureon_agent.cron_db` + `aureon_agent.cron_schedule` + `aureon_agent.cron_cli` to `[tool.setuptools] packages`
- [ ] **Tests** (`tests/test_cron.py`):
  - Schedule detection: cron/interval/at
  - Next-run calculation: cron expr, interval, ISO, timezone, staggering
  - DB CRUD: add/get/list/remove job, add/finish/list run
  - Scheduler _tick: due jobs run, non-due don't
  - _run_job: success path (mock agent returns text → delivered + rescheduled)
  - _run_job: timeout path (mock agent hangs → status='timeout' + notification)
  - _run_job: error path (mock agent raises → status='failed' + notification)
  - _run_job: stalled path (mock agent never calls LLM → status='failed', error='stalled')
  - One-shot auto-delete: `--repeat 1` job deleted after 1 run
  - Skill subset loading: only specified skills loaded
- [ ] **`docs/cron.md`** — user-facing docs:
  - What cron does
  - Schedule types with examples
  - CLI commands with examples
  - Heartbeat vs cron comparison table
  - Delivery options
  - Troubleshooting (stalled jobs, timeouts, missed runs)
- [ ] **`tasks/todo.md`** — add Phase 9 (Cron scheduler) with sub-tasks
- [ ] **`tasks/DEVLOG.md`** — add entry for this work
- [ ] **Live test via Telegram:**
  1. Create a one-shot job: `aureon-agent cron create "1m" --name "test" --prompt "Say hello" --deliver telegram --repeat 1`
  2. Wait 1 minute
  3. Verify Telegram received `📋 **test**\n\nHello! ...`
  4. Verify job auto-deleted from `cron list`
  5. Create a recurring job: `aureon-agent cron create "*/2 * * * *" --name "ping" --prompt "Say pong" --deliver telegram`
  6. Wait 2 minutes, verify 2 deliveries
  7. Remove: `aureon-agent cron remove <id>`
  8. Check runs: `aureon-agent cron runs <id>`

---

## Acceptance criteria

- [ ] `aureon-agent cron list` shows all jobs with schedule, next run, status
- [ ] `aureon-agent cron create "0 8 * * *" --name daily --prompt "..." --deliver telegram` creates a daily 8 AM job
- [ ] `aureon-agent cron create "30m" --name quick --prompt "..." --repeat 1` creates a one-shot 30-min reminder
- [ ] Cron jobs run in isolated sessions (no main session history leaks)
- [ ] Cron job output delivered to Telegram as `📋 **<name>**\n\n<output>`
- [ ] `aureon-agent cron pause/resume` works (paused jobs don't run)
- [ ] `aureon-agent cron run <id>` forces immediate execution on next tick
- [ ] `aureon-agent cron runs <id>` shows run history with status, duration, output snippet
- [ ] `aureon-agent cron status` shows scheduler alive + next tick
- [ ] One-shot jobs (`--repeat 1`) auto-delete after successful run
- [ ] Recurring jobs reschedule after each run
- [ ] Overdue jobs on bot restart are rescheduled to next future occurrence (not replayed)
- [ ] Timeout (300s default) aborts the run, logs `status='timeout'`, delivers timeout notification
- [ ] Stalled detection: no LLM call within 30s → `status='failed', error='stalled before first model call'`
- [ ] `--skills homelab-health` loads only that skill (not all 8)
- [ ] No `--skills` = bare agent (no skills loaded, tools still available)
- [ ] Top-of-hour staggering: `0 * * * *` jobs stagger by 0-5 min (unless `--exact`)
- [ ] `aureon-agent doctor` checks cron scheduler health
- [ ] All tests pass (`pytest tests/test_cron.py` — 12+ tests)
- [ ] Existing 13/13 tests still pass
- [ ] Bot restarts cleanly with cron jobs persisted
- [ ] Live Telegram test: one-shot job delivered in ~1 min, recurring job delivered every 2 min

## Out of scope (v1)

- **Heartbeat polling** (separate task, different architecture — cron is isolated, heartbeat is main-session)
- **Webhook-triggered jobs** (external triggers calling the bot — Phase 7 or later)
- **Gmail PubSub triggers** (OpenClaw has this, we don't need it yet)
- **Retry on failure** (`--retry N` for automatic retry — v2)
- **Per-job model override** (v2 — for now, all jobs use the agent's default model)
- **Cron job dependencies** (job A triggers job B — v2)
- **Concurrent job limit** (v1: unlimited concurrent jobs, v2: semaphore)
- **Job editing** (`aureon-agent cron edit <id> --schedule ...` — v2; for now, remove + recreate)
- **Cron job templates** (predefined job types — v2)
- **Timezone auto-detection** (v1: explicit `--tz` only)
- **Cron job import/export** (JSON backup/restore — v2)
- **Run output streaming** (v1: output sent as one message after completion; v2: optional streaming for long-running jobs)
- **Background task reconciliation** (OpenClaw's complex runtime-owned vs durable-history reconciliation — v1 is simpler: in-memory tracking + DB log)
- **Browser tab cleanup** (OpenClaw's browser automation cleanup — we don't have browser automation yet)
- **System event injection** (OpenClaw's `--system-event` for system-message injection — v2)
- **`--wake now`** (OpenClaw's immediate execution flag — use `cron run <id>` instead)

## Full spec references

- This file: `tasks/kickoff-cron-scheduler.md`
- OpenClaw cron reference: `~/.npm-global/lib/node_modules/openclaw/docs/automation/cron-jobs.md`
- OpenClaw cron vs heartbeat: `~/.npm-global/lib/node_modules/openclaw/docs/automation/cron-vs-heartbeat.md`
- OpenClaw cron CLI: `~/.npm-global/lib/node_modules/openclaw/docs/cli/cron.md`
- OpenClaw heartbeat: `~/.npm-global/lib/node_modules/openclaw/docs/gateway/heartbeat.md`
- Hermes cron: `hermes cron --help`, `hermes cron list` (live on athena)
- Existing aureon-agent patterns: `memory.py` (SQLite WAL), `session_manager.py` (sessions), `compaction/log.py` (audit log), `aureon_agent/subagent/log.py` (subagent audit), `agent_runtime.py` (ReAct loop), `channels/router.py` (delivery)
- Doctrine: `~/.openclaw/workspace/MEMORY.md` §Olympus + §Lessons
- Per-project AGENTS.md 6-rule contract