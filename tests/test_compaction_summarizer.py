import asyncio

import httpx

from compaction.log import CompactionLog, CompactionRun
from compaction.summarizer import MAX_OUTPUT_TOKENS, Summarizer


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def test_summarize_calls_llm_with_expected_prompt(monkeypatch):
    captured = {}

    class CapturingClient(_FakeClient):
        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["body"] = json
            return _FakeResponse({"choices": [{"message": {"content": "the summary"}}]})

    monkeypatch.setattr("compaction.summarizer.httpx.AsyncClient", CapturingClient)

    summarizer = Summarizer("http://127.0.0.1:11434/v1", model="minimax-m2.5:cloud")
    result = asyncio.run(summarizer.summarize([{"role": "user", "content": "hi"}]))

    assert result == "the summary"
    assert captured["url"] == "http://127.0.0.1:11434/v1/chat/completions"
    assert captured["body"]["max_tokens"] == MAX_OUTPUT_TOKENS
    assert captured["body"]["messages"][0]["role"] == "system"
    assert "200-word summary" in captured["body"]["messages"][0]["content"]


def test_summarize_timeout_falls_back_to_truncated_transcript(monkeypatch):
    class TimeoutClient(_FakeClient):
        async def post(self, url, headers=None, json=None):
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("compaction.summarizer.httpx.AsyncClient", TimeoutClient)

    summarizer = Summarizer("http://127.0.0.1:11434/v1")
    messages = [{"role": "user", "content": "x" * 1000}]
    result = asyncio.run(summarizer.summarize(messages))

    assert result.startswith("user: xxx")
    assert len(result) <= 500


def test_compaction_log_records_context_window(tmp_path):
    async def _run():
        log = CompactionLog(str(tmp_path / "compaction_log.db"))
        await log.connect()
        try:
            await log.record(CompactionRun(
                session_id="telegram:123",
                tokens_before=30_000,
                tokens_after=5_000,
                summary_text="summary",
                model_used="minimax-m2.5:cloud",
                context_window_used=32_768,
            ))
            runs = await log.list_recent(limit=1)
        finally:
            await log.close()
        return runs

    runs = asyncio.run(_run())
    assert len(runs) == 1
    assert runs[0].context_window_used == 32_768
    assert runs[0].status == "ok"
