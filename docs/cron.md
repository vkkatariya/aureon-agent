# Cron Scheduler

The cron scheduler runs as an asyncio task inside the bot process. It checks for due jobs every 60 seconds, spawns isolated agent runs, and delivers output to your configured channel (Telegram, Discord, or both).

## Quick start

```bash
# Create a one-shot reminder
aureon-agent cron create "1m" --name "test" --prompt "Say hello" --deliver telegram --repeat 1

# Create a recurring daily job
aureon-agent cron create "0 8 * * *" --name "morning-brief" --prompt "Summarize overnight updates" --deliver telegram

# Create a job every 30 minutes
aureon-agent cron create "30m" --name "check-health" --prompt "Check homelab container status" --deliver telegram

# List all jobs
aureon-agent cron list

# View run history
aureon-agent cron runs <job_id>
```

## Schedule types

| Type | Example | Description |
|---|---|---|
| `cron` | `0 8 * * *` | 5-field cron expression (minute hour day month weekday) |
| `cron` | `0 */6 * * *` | Every 6 hours |
| `cron` | `*/5 * * * *` | Every 5 minutes |
| `interval` | `30m` | Every 30 minutes |
| `interval` | `2h` | Every 2 hours |
| `interval` | `1d` | Every day |
| `at` | `2026-07-15T09:00:00` | One-shot ISO timestamp (auto-delete after run) |

### Cron expressions

Standard 5-field Vixie cron: `minute hour day-of-month month day-of-week`. Parsed by `croniter`.

Day-of-month and day-of-week use **OR logic** (standard Vixie behavior): `0 9 15 * 1` fires on every 15th AND every Monday, not only when the 15th is a Monday.

### Intervals

Simple shorthand: `Nm` (minutes), `Nh` (hours), `Nd` (days).

### One-shot timestamps

ISO 8601 format. Without timezone = UTC. Use `--tz Europe/Berlin` for local wall-clock.

### Top-of-hour staggering

Recurring cron expressions starting at `:00` are auto-staggered by up to 5 minutes to reduce load spikes. Use `--exact` to force precise timing.

## CLI commands

```bash
aureon-agent cron list                                # List all jobs
aureon-agent cron create <schedule> [options]          # Create a job
aureon-agent cron pause <job_id>                       # Disable a job (keep it)
aureon-agent cron resume <job_id>                      # Re-enable a paused job
aureon-agent cron run <job_id>                         # Force run on next tick
aureon-agent cron remove <job_id>                      # Delete a job
aureon-agent cron runs <job_id>                        # Run history for a job
aureon-agent cron status                               # Scheduler overview
```

### `cron create` options

| Option | Default | Description |
|---|---|---|
| `--name` | (required) | Human-readable job name |
| `--prompt` | (required) | Self-contained task instruction |
| `--skills` | (none) | Comma-separated skill names to load |
| `--deliver` | `telegram` | Delivery: `telegram`, `discord`, `local`, `all` |
| `--chat-id` | from `.env` | Telegram chat to deliver to |
| `--model` | agent default | Model override |
| `--timeout-sec` | `300` | Per-run timeout in seconds |
| `--repeat` | `0` (infinite) | N runs then auto-delete (1 = one-shot) |
| `--tz` | `UTC` | Timezone for cron expressions |
| `--exact` | off | Disable top-of-hour staggering |
| `--disabled` | off | Create as paused |

## Delivery

| Mode | Behavior |
|---|---|
| `telegram` | Send to Telegram chat (default) |
| `discord` | Send to Discord DM |
| `local` | No delivery — just log to `cron_runs` table |
| `all` | Fan out to all connected channels |

Output format: `📋 **<job_name>**\n\n<agent_output>` for chat channels.

Error notifications: `❌ Job '<name>' failed: <error>`
Timeout notifications: `⏰ Job '<name>' timed out after <N>s`

## Isolation

Each cron run is fully isolated:
- Fresh `session_id = cron:<job_id>:<timestamp>`
- No conversation history from main session
- No memory notes loaded
- Skills loaded per job spec only

The agent gets the same tools (terminal, file, web, etc.) but starts with a clean slate. The prompt must be self-contained.

## Skill loading per job

- `--skills homelab-health` → load only that skill
- `--skills homelab-health,notion` → load both
- No `--skills` → bare agent (no skills, tools still available)

## Timeout + error handling

| Condition | Status | Notification |
|---|---|---|
| Success | `success` | `📋 **name** output...` |
| Timeout (default 300s) | `timeout` | `⏰ Job timed out after Ns` |
| Exception | `failed` | `❌ Job failed: error` |

No retry in v1. Failed jobs are logged; next run happens on schedule.

## Restart behavior

- Jobs persist in `data/cron_jobs.db` (SQLite, WAL mode)
- On restart: scheduler reads all enabled jobs, resumes scheduling
- **Overdue recurring jobs:** rescheduled to next future occurrence (not replayed)
- **Overdue one-shot jobs (`--at`):** deleted (too late)

## Heartbeat vs cron

| | Heartbeat (future) | Cron (this feature) |
|---|---|---|
| **Trigger** | Polling (every ~30 min) | Exact schedule |
| **Context** | Main session (has history) | Isolated session (fresh) |
| **Use for** | Batch checks (email + calendar in one turn) | Exact timing, one-shot reminders, isolated tasks |
| **Token cost** | Lower (batch) | Higher (fresh session each time) |
| **Isolation** | None | Full |
| **Output** | Goes to main session | Delivered to configured channel |

Heartbeat is NOT implemented yet. Use cron for scheduled tasks.

## Health check

`aureon-agent doctor` includes a Cron Scheduler check that verifies:
- `data/cron_jobs.db` is readable
- Count of enabled jobs
- No stuck runs (status='running' for >10 min)

## Troubleshooting

### Job not firing
- Is the bot running? (`aureon-agent status`)
- Is the job enabled? (`aureon-agent cron list`)
- Check timezone (`--tz`) matches your intent
- Check `aureon-agent cron runs <id>` for error history

### Job fires but no delivery
- `--deliver local` means no chat delivery (just logged)
- Check `--chat-id` is correct (defaults to `TELEGRAM_ALLOWED_CHATS`)
- Check channel is connected (`aureon-agent doctor`)

### Stuck jobs
- `aureon-agent doctor` checks for runs stuck >10 min
- Default timeout is 300s — increase with `--timeout-sec`
- Check `aureon-agent cron runs <id>` for timeout/error status
