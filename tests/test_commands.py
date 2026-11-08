import asyncio
import logging

from channels.commands import run_cli


def test_run_cli_reports_errors_with_prefix(monkeypatch):
    def boom(*a, **k):
        raise OSError("nope")
    monkeypatch.setattr("channels.commands.subprocess.run", boom)
    out = asyncio.run(run_cli("doctor", ["doctor"], "!"))
    assert out == "Error running !doctor: nope"


def test_run_cli_empty_output(monkeypatch):
    class P:
        stdout = ""
        stderr = ""
    monkeypatch.setattr("channels.commands.subprocess.run", lambda *a, **k: P())
    assert asyncio.run(run_cli("logs", ["logs"])) == "(/logs produced no output)"


def test_httpx_logger_silenced_on_cli_import():
    import aureon_agent.cli  # noqa: F401
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
