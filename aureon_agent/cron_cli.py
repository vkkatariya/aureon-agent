"""CLI subcommands for aureon-agent cron management.

Wired into __main__.py as `aureon-agent cron <subcommand>`.
"""
import asyncio
import os
import time

from aureon_agent.cron_db import CronDB
from aureon_agent.cron_schedule import calc_next_run, detect_schedule_type

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "cron_jobs.db")


def _relative_time(ts: float | None) -> str:
    """Format a timestamp as a relative time string like 'in 2h 15m'."""
    if ts is None:
        return "—"
    diff = ts - time.time()
    if diff < 0:
        return "overdue"
    if diff < 60:
        return f"in {int(diff)}s"
    if diff < 3600:
        return f"in {int(diff // 60)}m"
    hours = int(diff // 3600)
    mins = int((diff % 3600) // 60)
    if hours < 24:
        return f"in {hours}h {mins}m"
    days = hours // 24
    return f"in {days}d {hours % 24}h"


def _format_ts(ts: float | None) -> str:
    """Format a timestamp for display."""
    if ts is None:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


async def _get_db() -> CronDB:
    db = CronDB(DB_PATH)
    await db.connect()
    return db


def cmd_cron(args):
    """Dispatch cron subcommands."""
    sub = args.cron_command
    if sub == "list":
        asyncio.run(_cmd_list(args))
    elif sub == "create":
        asyncio.run(_cmd_create(args))
    elif sub == "pause":
        asyncio.run(_cmd_pause(args))
    elif sub == "resume":
        asyncio.run(_cmd_resume(args))
    elif sub == "run":
        asyncio.run(_cmd_run(args))
    elif sub == "remove":
        asyncio.run(_cmd_remove(args))
    elif sub == "runs":
        asyncio.run(_cmd_runs(args))
    elif sub == "status":
        asyncio.run(_cmd_status(args))
    else:
        print(f"Unknown cron command: {sub}")


async def _cmd_list(args):
    from rich.console import Console
    from rich.table import Table

    db = await _get_db()
    try:
        jobs = await db.list_jobs()
    finally:
        await db.close()

    if not jobs:
        print("No cron jobs configured.")
        return

    console = Console()
    table = Table(title="Cron Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Schedule")
    table.add_column("Deliver")
    table.add_column("Next Run")
    table.add_column("Status")
    table.add_column("Runs", justify="right")

    for job in jobs:
        status = "[green]active[/green]" if job["enabled"] else "[yellow]paused[/yellow]"
        table.add_row(
            job["id"],
            job["name"],
            job["schedule"],
            job["deliver"],
            _relative_time(job["next_run_at"]),
            status,
            str(job["run_count"] or 0),
        )

    console.print(table)


async def _cmd_create(args):
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

    schedule = args.schedule
    schedule_type = detect_schedule_type(schedule)

    # Calculate first next_run_at
    now = time.time()
    next_run = calc_next_run(schedule, schedule_type, now,
                             tz=args.tz, exact=args.exact)

    # Parse skills
    skills = [s.strip() for s in args.skills.split(",") if s.strip()] if args.skills else []

    # Default chat_id from env
    chat_id = args.chat_id
    if not chat_id:
        chat_id = os.getenv("TELEGRAM_ALLOWED_CHATS", "").split(",")[0].strip() or None

    db = await _get_db()
    try:
        job = await db.add_job(
            name=args.name,
            schedule=schedule,
            schedule_type=schedule_type,
            prompt=args.prompt,
            skills=skills,
            deliver=args.deliver,
            chat_id=chat_id,
            model=args.model,
            timeout_sec=args.timeout_sec,
            repeat=args.repeat,
            enabled=not args.disabled,
            tz=args.tz,
            exact=args.exact,
            next_run_at=next_run,
        )
    finally:
        await db.close()

    print(f"Created job {job['id']}: {job['name']}, next run: {_relative_time(next_run)}")


async def _cmd_pause(args):
    db = await _get_db()
    try:
        job = await db.get_job(args.job_id)
        if not job:
            print(f"Job {args.job_id} not found")
            return
        await db.update_job(args.job_id, enabled=0)
    finally:
        await db.close()
    print(f"Paused job {args.job_id} ({job['name']})")


async def _cmd_resume(args):
    db = await _get_db()
    try:
        job = await db.get_job(args.job_id)
        if not job:
            print(f"Job {args.job_id} not found")
            return

        # Recalculate next_run_at
        now = time.time()
        next_run = calc_next_run(
            job["schedule"], job["schedule_type"], now,
            tz=job.get("tz", "UTC"),
            exact=bool(job.get("exact", 0)),
        )
        await db.update_job(args.job_id, enabled=1, next_run_at=next_run)
    finally:
        await db.close()
    print(f"Resumed job {args.job_id} ({job['name']}), next run: {_relative_time(next_run)}")


async def _cmd_run(args):
    db = await _get_db()
    try:
        job = await db.get_job(args.job_id)
        if not job:
            print(f"Job {args.job_id} not found")
            return
        # Force run on next tick by setting next_run_at to now
        await db.update_job(args.job_id, next_run_at=time.time(), enabled=1)
    finally:
        await db.close()
    print(f"Job {args.job_id} ({job['name']}) queued for next scheduler tick")


async def _cmd_remove(args):
    db = await _get_db()
    try:
        job = await db.get_job(args.job_id)
        if not job:
            print(f"Job {args.job_id} not found")
            return
        removed = await db.remove_job(args.job_id)
    finally:
        await db.close()
    if removed:
        print(f"Removed job {args.job_id} ({job['name']}). Run history preserved.")
    else:
        print(f"Failed to remove job {args.job_id}")


async def _cmd_runs(args):
    from rich.console import Console
    from rich.table import Table

    db = await _get_db()
    try:
        runs = await db.list_runs(args.job_id, limit=args.last)
        job = await db.get_job(args.job_id)
    finally:
        await db.close()

    job_name = job["name"] if job else args.job_id

    if not runs:
        print(f"No runs found for job {args.job_id}")
        return

    console = Console()
    table = Table(title=f"Run History: {job_name}")
    table.add_column("Started")
    table.add_column("Status")
    table.add_column("Duration")
    table.add_column("Output", overflow="fold", max_width=80)
    table.add_column("Error", overflow="fold", max_width=40)

    for run in runs:
        output = run.get("output") or ""
        if len(output) > 80:
            output = output[:77] + "..."
        error = run.get("error") or ""
        if len(error) > 40:
            error = error[:37] + "..."

        status_color = {
            "success": "green",
            "failed": "red",
            "timeout": "yellow",
            "running": "blue",
        }.get(run["status"], "white")

        table.add_row(
            _format_ts(run["started_at"]),
            f"[{status_color}]{run['status']}[/{status_color}]",
            f"{run.get('duration_sec', 0) or 0:.1f}s",
            output,
            error,
        )

    console.print(table)


async def _cmd_status(args):
    """Show scheduler status — requires reading the DB for job counts."""
    db = await _get_db()
    try:
        jobs = await db.list_jobs()
    finally:
        await db.close()

    enabled = [j for j in jobs if j["enabled"]]
    paused = [j for j in jobs if not j["enabled"]]

    now = time.time()
    due_now = [j for j in enabled if j.get("next_run_at") and j["next_run_at"] <= now]

    # Next scheduled job
    future_jobs = [j for j in enabled if j.get("next_run_at") and j["next_run_at"] > now]
    next_job = min(future_jobs, key=lambda j: j["next_run_at"]) if future_jobs else None

    print("Cron Scheduler Status")
    print("=" * 40)
    print(f"  Total jobs:    {len(jobs)}")
    print(f"  Active:        {len(enabled)}")
    print(f"  Paused:        {len(paused)}")
    print(f"  Due now:       {len(due_now)}")
    if next_job:
        print(f"  Next run:      {next_job['name']} ({_relative_time(next_job['next_run_at'])})")
    else:
        print("  Next run:      —")
    print()
    print("Note: Scheduler runs inside the bot process.")
    print("Start the bot with `aureon-agent start` to activate the scheduler.")


def register_cron_subparser(subparsers):
    """Register the 'cron' subcommand group with the main argparse parser."""
    p_cron = subparsers.add_parser("cron", help="Manage cron jobs")
    cron_sub = p_cron.add_subparsers(dest="cron_command")

    # cron list
    cron_sub.add_parser("list", help="List all cron jobs")

    # cron create
    p_create = cron_sub.add_parser("create", help="Create a new cron job")
    p_create.add_argument("schedule", help="Schedule: cron expr, interval (30m/2h/1d), or ISO timestamp")
    p_create.add_argument("--name", required=True, help="Job name")
    p_create.add_argument("--prompt", required=True, help="Self-contained task instruction")
    p_create.add_argument("--skills", default="", help="Comma-separated skill names")
    p_create.add_argument("--deliver", default="telegram",
                          choices=["telegram", "discord", "local", "all"],
                          help="Delivery channel (default: telegram)")
    p_create.add_argument("--chat-id", default=None, help="Chat ID for delivery")
    p_create.add_argument("--model", default=None, help="Model override")
    p_create.add_argument("--timeout-sec", type=int, default=300, help="Per-run timeout (default: 300)")
    p_create.add_argument("--repeat", type=int, default=0,
                          help="Run N times then delete (0=infinite, 1=one-shot)")
    p_create.add_argument("--tz", default="UTC", help="Timezone for cron expressions")
    p_create.add_argument("--exact", action="store_true", help="Disable top-of-hour staggering")
    p_create.add_argument("--disabled", action="store_true", help="Create as paused")

    # cron pause
    p_pause = cron_sub.add_parser("pause", help="Pause a job")
    p_pause.add_argument("job_id", help="Job ID to pause")

    # cron resume
    p_resume = cron_sub.add_parser("resume", help="Resume a paused job")
    p_resume.add_argument("job_id", help="Job ID to resume")

    # cron run
    p_run = cron_sub.add_parser("run", help="Force run a job on next tick")
    p_run.add_argument("job_id", help="Job ID to run")

    # cron remove
    p_remove = cron_sub.add_parser("remove", help="Remove a job (keeps run history)")
    p_remove.add_argument("job_id", help="Job ID to remove")

    # cron runs
    p_runs = cron_sub.add_parser("runs", help="Show run history for a job")
    p_runs.add_argument("job_id", help="Job ID")
    p_runs.add_argument("--last", type=int, default=20, help="Number of runs to show")

    # cron status
    cron_sub.add_parser("status", help="Scheduler status overview")

    return p_cron
