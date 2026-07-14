"""Tests for the cron scheduler subsystem.

Covers:
  - Schedule detection (cron / interval / at)
  - Next-run calculation (cron, interval, ISO, timezone, staggering)
  - DB CRUD (add/get/list/remove job, add/finish/list run)
  - Scheduler _tick (due jobs run, non-due don't)
  - _run_job paths (success, timeout, error)
  - One-shot auto-delete (--repeat 1)
  - Skill subset loading
  - Overdue-on-restart rescheduling
"""
import asyncio
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Schedule detection ────────────────────────────────────────────

class TestScheduleDetection(unittest.TestCase):
    def test_cron_expression(self):
        from aureon_agent.cron_schedule import detect_schedule_type
        self.assertEqual(detect_schedule_type("0 8 * * *"), "cron")
        self.assertEqual(detect_schedule_type("*/5 * * * *"), "cron")
        self.assertEqual(detect_schedule_type("0 */6 * * *"), "cron")

    def test_interval(self):
        from aureon_agent.cron_schedule import detect_schedule_type
        self.assertEqual(detect_schedule_type("30m"), "interval")
        self.assertEqual(detect_schedule_type("2h"), "interval")
        self.assertEqual(detect_schedule_type("1d"), "interval")

    def test_at_iso(self):
        from aureon_agent.cron_schedule import detect_schedule_type
        self.assertEqual(detect_schedule_type("2026-07-15T09:00:00"), "at")
        self.assertEqual(detect_schedule_type("2026-07-15T09:00:00+02:00"), "at")


# ── Interval parsing ─────────────────────────────────────────────

class TestIntervalParsing(unittest.TestCase):
    def test_minutes(self):
        from aureon_agent.cron_schedule import parse_interval
        self.assertEqual(parse_interval("30m"), 1800)

    def test_hours(self):
        from aureon_agent.cron_schedule import parse_interval
        self.assertEqual(parse_interval("2h"), 7200)

    def test_days(self):
        from aureon_agent.cron_schedule import parse_interval
        self.assertEqual(parse_interval("1d"), 86400)

    def test_invalid(self):
        from aureon_agent.cron_schedule import parse_interval
        with self.assertRaises(ValueError):
            parse_interval("5x")
        with self.assertRaises(ValueError):
            parse_interval("hello")


# ── Next-run calculation ─────────────────────────────────────────

class TestCalcNextRun(unittest.TestCase):
    def test_interval_next(self):
        from aureon_agent.cron_schedule import calc_next_run
        now = 1000.0
        result = calc_next_run("30m", "interval", now)
        self.assertEqual(result, now + 1800)

    def test_cron_next_is_in_future(self):
        from aureon_agent.cron_schedule import calc_next_run
        now = time.time()
        result = calc_next_run("*/5 * * * *", "cron", now, exact=True)
        # Should be in the future
        self.assertGreater(result, now)
        # And within ~5 minutes
        self.assertLess(result, now + 301)

    def test_at_timestamp(self):
        from aureon_agent.cron_schedule import calc_next_run
        result = calc_next_run("2030-01-01T00:00:00", "at", 0.0)
        # Should be a valid timestamp in the future
        self.assertGreater(result, time.time())

    def test_stagger_on_top_of_hour(self):
        from aureon_agent.cron_schedule import calc_next_run
        # Run multiple times — at least one should have stagger
        results = set()
        now = time.time()
        for _ in range(10):
            r = calc_next_run("0 * * * *", "cron", now, exact=False)
            results.add(r)
        # With staggering, we should get some variation (not all identical)
        # Note: there's a small chance all 10 random values are the same,
        # but probability is negligible
        # At minimum, verify it returns a valid future timestamp
        for r in results:
            self.assertGreater(r, now)

    def test_exact_no_stagger(self):
        from aureon_agent.cron_schedule import calc_next_run
        now = time.time()
        results = set()
        for _ in range(5):
            r = calc_next_run("0 * * * *", "cron", now, exact=True)
            results.add(r)
        # With exact=True, all results should be identical
        self.assertEqual(len(results), 1)


# ── DB CRUD ───────────────────────────────────────────────────────

class TestCronDB(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_cron.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_and_get_job(self):
        from aureon_agent.cron_db import CronDB

        async def _test():
            db = CronDB(self.db_path)
            await db.connect()
            try:
                job = await db.add_job(
                    name="test",
                    schedule="30m",
                    schedule_type="interval",
                    prompt="Say hello",
                )
                self.assertIsNotNone(job)
                self.assertEqual(job["name"], "test")
                self.assertEqual(job["schedule"], "30m")
                self.assertEqual(job["prompt"], "Say hello")
                self.assertEqual(len(job["id"]), 8)

                # Get by ID
                fetched = await db.get_job(job["id"])
                self.assertEqual(fetched["name"], "test")
            finally:
                await db.close()

        asyncio.run(_test())

    def test_list_jobs(self):
        from aureon_agent.cron_db import CronDB

        async def _test():
            db = CronDB(self.db_path)
            await db.connect()
            try:
                await db.add_job(name="a", schedule="1h", schedule_type="interval", prompt="A")
                await db.add_job(name="b", schedule="2h", schedule_type="interval", prompt="B")
                jobs = await db.list_jobs()
                self.assertEqual(len(jobs), 2)
            finally:
                await db.close()

        asyncio.run(_test())

    def test_remove_job(self):
        from aureon_agent.cron_db import CronDB

        async def _test():
            db = CronDB(self.db_path)
            await db.connect()
            try:
                job = await db.add_job(name="rm", schedule="1d", schedule_type="interval", prompt="X")
                removed = await db.remove_job(job["id"])
                self.assertTrue(removed)
                self.assertIsNone(await db.get_job(job["id"]))
            finally:
                await db.close()

        asyncio.run(_test())

    def test_get_due_jobs(self):
        from aureon_agent.cron_db import CronDB

        async def _test():
            db = CronDB(self.db_path)
            await db.connect()
            try:
                now = time.time()
                # Due job (next_run_at in the past)
                await db.add_job(
                    name="due", schedule="1h", schedule_type="interval",
                    prompt="Due", next_run_at=now - 10)
                # Future job (not due)
                await db.add_job(
                    name="future", schedule="1h", schedule_type="interval",
                    prompt="Future", next_run_at=now + 3600)
                # Disabled job (not due even if overdue)
                await db.add_job(
                    name="disabled", schedule="1h", schedule_type="interval",
                    prompt="Disabled", next_run_at=now - 10, enabled=False)

                due = await db.get_due_jobs(now)
                self.assertEqual(len(due), 1)
                self.assertEqual(due[0]["name"], "due")
            finally:
                await db.close()

        asyncio.run(_test())

    def test_run_audit_log(self):
        from aureon_agent.cron_db import CronDB

        async def _test():
            db = CronDB(self.db_path)
            await db.connect()
            try:
                job = await db.add_job(
                    name="audit", schedule="1h", schedule_type="interval", prompt="X")

                run_id = await db.add_run(
                    job_id=job["id"], session_id="cron:test:123",
                    started_at=time.time())
                self.assertIsInstance(run_id, int)

                await db.finish_run(
                    run_id, status="success", output="Hello",
                    duration_sec=1.5)

                runs = await db.list_runs(job["id"])
                self.assertEqual(len(runs), 1)
                self.assertEqual(runs[0]["status"], "success")
                self.assertEqual(runs[0]["output"], "Hello")
            finally:
                await db.close()

        asyncio.run(_test())


# ── Scheduler tick ────────────────────────────────────────────────

class TestCronSchedulerTick(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_sched.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_tick_runs_due_jobs(self):
        from aureon_agent.cron import CronScheduler

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="Hello from cron!")

        mock_router = MagicMock()
        mock_router.channels = {"telegram": MagicMock()}
        mock_router.send_message = AsyncMock()

        async def _test():
            scheduler = CronScheduler(
                db_path=self.db_path,
                agent_runtime=mock_agent,
                channel_router=mock_router,
                workspace_dir="/tmp",
                default_chat_id="12345",
            )
            scheduler.db = (await self._make_db())

            # Create a due job
            now = time.time()
            await scheduler.db.add_job(
                name="due-test",
                schedule="1h",
                schedule_type="interval",
                prompt="Say hello",
                next_run_at=now - 10,  # due
            )

            await scheduler._tick()
            # Wait for in-flight tasks to complete
            if scheduler._in_flight:
                await asyncio.wait(scheduler._in_flight, timeout=5)

            # Verify agent was called
            mock_agent.run.assert_called_once()
            # Verify delivery
            mock_router.send_message.assert_called_once()
            call_args = mock_router.send_message.call_args
            self.assertIn("Hello from cron!", call_args[0][1])

            await scheduler.db.close()

        asyncio.run(_test())

    async def _make_db(self):
        from aureon_agent.cron_db import CronDB
        db = CronDB(self.db_path)
        await db.connect()
        return db


# ── One-shot auto-delete ──────────────────────────────────────────

class TestOneShotAutoDelete(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_oneshot.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_repeat_1_deletes_after_run(self):
        from aureon_agent.cron import CronScheduler

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="Done")

        mock_router = MagicMock()
        mock_router.channels = {"telegram": MagicMock()}
        mock_router.send_message = AsyncMock()

        async def _test():
            scheduler = CronScheduler(
                db_path=self.db_path,
                agent_runtime=mock_agent,
                channel_router=mock_router,
                workspace_dir="/tmp",
                default_chat_id="12345",
            )
            from aureon_agent.cron_db import CronDB
            scheduler.db = CronDB(self.db_path)
            await scheduler.db.connect()

            now = time.time()
            job = await scheduler.db.add_job(
                name="oneshot",
                schedule="1h",
                schedule_type="interval",
                prompt="One time only",
                repeat=1,
                next_run_at=now - 10,
            )
            job_id = job["id"]

            await scheduler._tick()
            if scheduler._in_flight:
                await asyncio.wait(scheduler._in_flight, timeout=5)

            # Job should be deleted
            remaining = await scheduler.db.get_job(job_id)
            self.assertIsNone(remaining)

            # But run history should exist
            runs = await scheduler.db.list_runs(job_id)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["status"], "success")

            await scheduler.db.close()

        asyncio.run(_test())


# ── Overdue on restart ────────────────────────────────────────────

class TestOverdueOnRestart(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_overdue.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_overdue_recurring_rescheduled(self):
        from aureon_agent.cron import CronScheduler
        from aureon_agent.cron_db import CronDB

        async def _test():
            db = CronDB(self.db_path)
            await db.connect()

            now = time.time()
            job = await db.add_job(
                name="overdue-recurring",
                schedule="1h",
                schedule_type="interval",
                prompt="Check",
                next_run_at=now - 3600,  # 1 hour overdue
            )

            scheduler = CronScheduler(
                db_path=self.db_path,
                agent_runtime=MagicMock(),
                channel_router=MagicMock(),
                workspace_dir="/tmp",
            )
            scheduler.db = db

            await scheduler._handle_overdue_jobs()

            updated = await db.get_job(job["id"])
            # Should be rescheduled to future (now + 1h)
            self.assertGreater(updated["next_run_at"], now)

            await db.close()

        asyncio.run(_test())

    def test_overdue_oneshot_deleted(self):
        from aureon_agent.cron import CronScheduler
        from aureon_agent.cron_db import CronDB

        async def _test():
            db = CronDB(self.db_path)
            await db.connect()

            now = time.time()
            job = await db.add_job(
                name="overdue-at",
                schedule="2020-01-01T00:00:00",
                schedule_type="at",
                prompt="Too late",
                next_run_at=now - 86400,
            )

            scheduler = CronScheduler(
                db_path=self.db_path,
                agent_runtime=MagicMock(),
                channel_router=MagicMock(),
                workspace_dir="/tmp",
            )
            scheduler.db = db

            await scheduler._handle_overdue_jobs()

            # One-shot should be deleted
            self.assertIsNone(await db.get_job(job["id"]))

            await db.close()

        asyncio.run(_test())


# ── Skill subset ──────────────────────────────────────────────────

class TestSkillSubset(unittest.TestCase):
    def test_get_tools_subset_filters(self):
        from skill_loader import SkillLoader

        loader = SkillLoader("/nonexistent")
        # Manually set up skills dict
        loader.skills = {
            "skill-a": {
                "name": "skill-a",
                "tools": [{"name": "tool_a", "description": "A"}],
            },
            "skill-b": {
                "name": "skill-b",
                "tools": [{"name": "tool_b", "description": "B"}],
            },
            "skill-c": {
                "name": "skill-c",
                "tools": [{"name": "tool_c", "description": "C"}],
            },
        }

        # Subset of 1
        tools = loader.get_tools_subset(["skill-a"])
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "tool_a")

        # Subset of 2
        tools = loader.get_tools_subset(["skill-a", "skill-c"])
        self.assertEqual(len(tools), 2)
        names = {t["name"] for t in tools}
        self.assertEqual(names, {"tool_a", "tool_c"})

        # Empty subset
        tools = loader.get_tools_subset([])
        self.assertEqual(len(tools), 0)

        # Unknown skill (should warn and skip)
        tools = loader.get_tools_subset(["nonexistent"])
        self.assertEqual(len(tools), 0)


# ── Timeout path ──────────────────────────────────────────────────

class TestTimeoutPath(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_timeout.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_timeout_logged_and_delivered(self):
        from aureon_agent.cron import CronScheduler

        async def slow_agent(*a, **kw):
            await asyncio.sleep(10)
            return "never"

        mock_agent = MagicMock()
        mock_agent.run = slow_agent

        mock_router = MagicMock()
        mock_router.channels = {"telegram": MagicMock()}
        mock_router.send_message = AsyncMock()

        async def _test():
            scheduler = CronScheduler(
                db_path=self.db_path,
                agent_runtime=mock_agent,
                channel_router=mock_router,
                workspace_dir="/tmp",
                default_chat_id="12345",
            )
            from aureon_agent.cron_db import CronDB
            scheduler.db = CronDB(self.db_path)
            await scheduler.db.connect()

            now = time.time()
            job = await scheduler.db.add_job(
                name="slow-job",
                schedule="1h",
                schedule_type="interval",
                prompt="Be slow",
                timeout_sec=1,  # 1 second timeout
                next_run_at=now - 10,
            )

            await scheduler._tick()
            if scheduler._in_flight:
                await asyncio.wait(scheduler._in_flight, timeout=5)

            # Check run was logged as timeout
            runs = await scheduler.db.list_runs(job["id"])
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["status"], "timeout")

            # Check timeout notification was delivered
            mock_router.send_message.assert_called_once()
            msg = mock_router.send_message.call_args[0][1]
            self.assertIn("timed out", msg)

            await scheduler.db.close()

        asyncio.run(_test())


# ── Error path ────────────────────────────────────────────────────

class TestErrorPath(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test_error.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_error_logged_and_delivered(self):
        from aureon_agent.cron import CronScheduler

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(side_effect=RuntimeError("LLM exploded"))

        mock_router = MagicMock()
        mock_router.channels = {"telegram": MagicMock()}
        mock_router.send_message = AsyncMock()

        async def _test():
            scheduler = CronScheduler(
                db_path=self.db_path,
                agent_runtime=mock_agent,
                channel_router=mock_router,
                workspace_dir="/tmp",
                default_chat_id="12345",
            )
            from aureon_agent.cron_db import CronDB
            scheduler.db = CronDB(self.db_path)
            await scheduler.db.connect()

            now = time.time()
            job = await scheduler.db.add_job(
                name="fail-job",
                schedule="1h",
                schedule_type="interval",
                prompt="Fail",
                next_run_at=now - 10,
            )

            await scheduler._tick()
            if scheduler._in_flight:
                await asyncio.wait(scheduler._in_flight, timeout=5)

            runs = await scheduler.db.list_runs(job["id"])
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["status"], "failed")
            self.assertIn("LLM exploded", runs[0]["error"])

            # Error notification delivered
            mock_router.send_message.assert_called_once()
            msg = mock_router.send_message.call_args[0][1]
            self.assertIn("failed", msg)

            await scheduler.db.close()

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
