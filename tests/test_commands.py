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
        returncode = 0
    monkeypatch.setattr("channels.commands.subprocess.run", lambda *a, **k: P())
    assert asyncio.run(run_cli("logs", ["logs"])) == "(/logs produced no output)"


def test_token_redacted_from_any_logger():
    import io
    from aureon_agent.logsafe import RedactTokenFilter
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.addFilter(RedactTokenFilter())
    lg = logging.getLogger("some.other.logger")
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    try:
        tok = "123456789:" + "A" * 35
        lg.info("POST https://api.telegram.org/bot%s/getUpdates", tok)
    finally:
        lg.removeHandler(h)
    out = buf.getvalue()
    assert tok not in out and "bot<redacted>/getUpdates" in out


def test_run_cli_timeout_hides_interpreter_path(monkeypatch):
    import subprocess

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(["/usr/bin/python", "-m", "x"], 60)
    monkeypatch.setattr("channels.commands.subprocess.run", slow)
    out = asyncio.run(run_cli("doctor", ["doctor"], ""))
    assert out == "Error running doctor: timed out after 60s"
