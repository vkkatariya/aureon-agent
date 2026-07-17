"""Cron scheduler — asyncio background task that runs inside the bot process.

Ticks every 60s, checks for due jobs, spawns isolated agent runs,
delivers output to the configured channel.
"""
import asyncio
import logging
import time

from aureon_agent.cron_db import CronDB
from aureon_agent.cron_schedule import calc_next_run

logger = logging.getLogger(__name__)

TICK_INTERVAL = 60  # seconds between scheduler ticks
STALL_TIMEOUT = 30  # seconds before declaring a job stalled
GRACE_PERIOD = 30   # seconds to wait for in-flight jobs on shutdown


class CronScheduler:
    """Background scheduler that runs cron jobs as isolated agent turns.

    Lifecycle:
        scheduler = CronScheduler(...)
        await scheduler.start()   # starts the 60s tick loop
        ...
        await scheduler.stop()    # graceful shutdown
    """

    def __init__(self, db_path: str, agent_runtime, channel_router,
                 workspace_dir: str, default_chat_id: str = ""):
        self.db_path = db_path
        self.agent = agent_runtime
        self.router = channel_router
        self.workspace_dir = workspace_dir
        self.default_chat_id = default_chat_id
        self.db: CronDB | None = None
        self._loop_task: asyncio.Task | None = None
        self._in_flight: set[asyncio.Task] = set()
        self._last_tick: float | None = None
        self._running = False

    async def start(self):
        """Initialize DB and start the scheduler loop."""
        self.db = CronDB(self.db_path)
        await self.db.connect()

        # Handle overdue jobs on startup
        await self._handle_overdue_jobs()

        self._running = True
        self._loop_task = asyncio.create_task(self._loop())
        logger.info("cron scheduler started")

    async def stop(self):
        """Graceful shutdown: cancel loop, wait for in-flight jobs."""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

        # Wait for in-flight jobs (best-effort, GRACE_PERIOD seconds)
        if self._in_flight:
            logger.info("cron: waiting for %d in-flight jobs (max %ds)",
                        len(self._in_flight), GRACE_PERIOD)
            _, pending = await asyncio.wait(
                self._in_flight, timeout=GRACE_PERIOD)
            for task in pending:
                task.cancel()

        if self.db:
            await self.db.close()
        logger.info("cron scheduler stopped")

    async def _loop(self):
        """Main scheduler loop — ticks every TICK_INTERVAL seconds."""
        while self._running:
            try:
                await self._tick()
            except Exception:
                logger.exception("cron: tick failed")
            await asyncio.sleep(TICK_INTERVAL)

    async def _tick(self):
        """One scheduler tick: find due jobs and spawn them."""
        now = time.time()
        self._last_tick = now

        due_jobs = await self.db.get_due_jobs(now)
        if due_jobs:
            logger.info("cron: tick found %d due job(s)", len(due_jobs))

        for job in due_jobs:
            task = asyncio.create_task(self._run_job(job))
            self._in_flight.add(task)
            task.add_done_callback(self._in_flight.discard)

    async def _run_job(self, job: dict):
        """Execute a single cron job as an isolated agent turn."""
        job_id = job["id"]
        started = time.time()
        session_id = f"cron:{job_id}:{int(started)}"

        logger.info("cron: starting job %s (%s)", job_id, job["name"])

        # Insert run record
        run_id = await self.db.add_run(
            job_id=job_id, session_id=session_id, started_at=started)

        output = None
        status = "success"
        error = None

        try:
            # Build callbacks — no streaming for cron jobs
            callbacks = {
                "on_token": None,
                "on_tool_use": None,
                "context": {
                    "router": self.router,
                    "session_id": session_id,
                    "channel_name": "cron",
                    "client_id": job_id,
                },
            }

            # Build history — single user message (isolated, no history)
            history = [{"role": "user", "content": job["prompt"]}]

            # Run with timeout
            timeout = job.get("timeout_sec", 300) or 300
            output = await asyncio.wait_for(
                self.agent.run(history, session_id, callbacks),
                timeout=timeout,
            )
            status = "success"

        except asyncio.TimeoutError:
            status = "timeout"
            error = f"Job timed out after {job.get('timeout_sec', 300)}s"
            logger.warning("cron: job %s (%s) timed out", job_id, job["name"])

        except Exception as e:
            status = "failed"
            error = str(e)
            logger.error("cron: job %s (%s) failed: %s",
                         job_id, job["name"], e)

        # Record the run result
        duration = time.time() - started
        await self.db.finish_run(
            run_id, status=status, output=output,
            error=error, duration_sec=duration)

        # Deliver the output
        await self._deliver(job, status, output, error, duration)

        # Reschedule or delete
        await self._reschedule(job, status)

        logger.info("cron: job %s (%s) finished — status=%s duration=%.1fs",
                     job_id, job["name"], status, duration)

    async def _deliver(self, job: dict, status: str, output: str | None,
                       error: str | None, duration: float):
        """Deliver the job result to the configured channel."""
        deliver = job.get("deliver", "telegram")

        if deliver == "local":
            # No delivery — just logged to cron_runs
            return

        # Build the delivery message
        if status == "success" and output:
            text = f"📋 **{job['name']}**\n\n{output}"
        elif status == "timeout":
            text = f"⏰ Job '{job['name']}' timed out after {job.get('timeout_sec', 300)}s"
        elif status == "failed":
            text = f"❌ Job '{job['name']}' failed: {error or 'unknown error'}"
        else:
            # No output — skip delivery
            return

        # Determine chat_id
        chat_id = job.get("chat_id") or self.default_chat_id
        if not chat_id:
            logger.warning("cron: no chat_id for job %s, skipping delivery",
                           job["id"])
            return

        try:
            if deliver == "all":
                # Fan out to all connected channels
                for channel_name in self.router.channels:
                    session_key = f"{channel_name}:{chat_id}"
                    await self.router.send_message(session_key, text)
            elif deliver in ("telegram", "discord"):
                session_key = f"{deliver}:{chat_id}"
                await self.router.send_message(session_key, text)
            else:
                logger.warning("cron: unknown deliver type %r for job %s",
                               deliver, job["id"])
        except Exception as e:
            logger.error("cron: delivery failed for job %s: %s",
                         job["id"], e)

    async def _reschedule(self, job: dict, status: str):
        """Reschedule or delete the job after a run."""
        job_id = job["id"]
        schedule_type = job["schedule_type"]
        now = time.time()

        # One-shot 'at' jobs: always delete after run
        if schedule_type == "at":
            await self.db.remove_job(job_id)
            logger.info("cron: one-shot job %s (%s) removed after run",
                         job_id, job["name"])
            return

        # Check repeat count
        run_count = (job.get("run_count") or 0) + 1
        repeat = job.get("repeat", 0) or 0

        if repeat > 0 and run_count >= repeat:
            await self.db.remove_job(job_id)
            logger.info("cron: job %s (%s) removed — repeat count %d reached",
                         job_id, job["name"], repeat)
            return

        # Calculate next run
        next_run = calc_next_run(
            job["schedule"], schedule_type, now,
            tz=job.get("tz", "UTC"),
            exact=bool(job.get("exact", 0)),
        )

        await self.db.update_job(
            job_id,
            last_run_at=now,
            next_run_at=next_run,
            run_count=run_count,
        )

    async def _handle_overdue_jobs(self):
        """On startup, reschedule overdue jobs to next future occurrence.

        Per OpenClaw behavior: overdue isolated agent-turn jobs are rescheduled
        instead of replaying immediately.
        """
        now = time.time()
        jobs = await self.db.list_jobs()
        for job in jobs:
            if not job.get("enabled"):
                continue
            next_run = job.get("next_run_at")
            if next_run is None:
                continue
            if next_run > now:
                continue  # Not overdue

            # One-shot 'at' jobs that are overdue: delete them
            if job["schedule_type"] == "at":
                await self.db.remove_job(job["id"])
                logger.warning(
                    "cron: one-shot job %s (%s) was overdue (scheduled %s), "
                    "deleted — too late",
                    job["id"], job["name"],
                    time.strftime("%Y-%m-%d %H:%M:%S",
                                 time.gmtime(next_run)))
                continue

            # Recurring jobs: reschedule to next future occurrence
            new_next = calc_next_run(
                job["schedule"], job["schedule_type"], now,
                tz=job.get("tz", "UTC"),
                exact=bool(job.get("exact", 0)),
            )
            await self.db.update_job(job["id"], next_run_at=new_next)
            logger.info(
                "cron: overdue job %s (%s) rescheduled from %s to %s",
                job["id"], job["name"],
                time.strftime("%H:%M:%S", time.gmtime(next_run)),
                time.strftime("%H:%M:%S", time.gmtime(new_next)))

    # ── Status introspection ──────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running and self._loop_task is not None

    @property
    def last_tick(self) -> float | None:
        return self._last_tick

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)
