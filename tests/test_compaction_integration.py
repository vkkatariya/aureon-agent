import asyncio
import logging

import tiktoken

from agent_runtime import AgentRuntime

_ENC = tiktoken.get_encoding("cl100k_base")
_BASE_IDS = _ENC.encode("The quick brown fox jumps over the lazy dog. ")


def _text_with_token_count(n):
    ids = (_BASE_IDS * (n // len(_BASE_IDS) + 1))[:n]
    return _ENC.decode(ids)


def _make_agent():
    return AgentRuntime(
        base_url="http://127.0.0.1:11434/v1",
        api_key=None,
        model="minimax-m2.5:cloud",
        skill_loader=None,
        workspace_dir="/nonexistent",
        memory=None,
    )


def _long_history(n_messages=200, content_len=2000):
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": "x" * content_len} for i in range(n_messages)]


def test_short_history_no_compaction_regardless_of_model(monkeypatch):
    monkeypatch.setenv("AUREON_COMPACTION_ENABLED", "1")
    agent = _make_agent()
    messages = [{"role": "user", "content": "hi"}]

    result = asyncio.run(agent._maybe_compact(messages, "session1", "system prompt"))

    assert result == messages
    assert agent.compactions_run_total == 0


def test_long_history_small_context_model_compacts(monkeypatch):
    monkeypatch.setenv("AUREON_COMPACTION_ENABLED", "1")
    agent = _make_agent()
    agent.model = "minimax-m2.5:cloud"  # 32K window

    async def fake_summarize(self, messages):
        return "fake summary"

    monkeypatch.setattr("compaction.summarizer.Summarizer.summarize", fake_summarize)

    messages = _long_history()
    result = asyncio.run(agent._maybe_compact(messages, "session1", "system prompt"))

    assert agent.compactions_run_total == 1
    assert result[0]["role"] == "system"
    assert "fake summary" in result[0]["content"]
    assert len(result) < len(messages)


def test_long_history_huge_context_model_no_compaction(monkeypatch):
    monkeypatch.setenv("AUREON_COMPACTION_ENABLED", "1")
    agent = _make_agent()
    agent.model = "claude-sonnet-4[1m]"  # 1M window, plenty of room

    messages = _long_history()
    result = asyncio.run(agent._maybe_compact(messages, "session1", "system prompt"))

    assert result == messages
    assert agent.compactions_run_total == 0


def test_compaction_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AUREON_COMPACTION_ENABLED", raising=False)
    agent = _make_agent()
    agent.model = "minimax-m2.5:cloud"

    messages = _long_history()
    result = asyncio.run(agent._maybe_compact(messages, "session1", "system prompt"))

    assert result == messages
    assert agent.compactions_run_total == 0


def test_system_prompt_too_big_skips_with_error_log(monkeypatch, caplog):
    monkeypatch.setenv("AUREON_COMPACTION_ENABLED", "1")
    agent = _make_agent()
    agent.model = "minimax-m2.5:cloud"

    huge_system_prompt = _text_with_token_count(20_000)
    messages = _long_history()

    with caplog.at_level(logging.ERROR):
        result = asyncio.run(agent._maybe_compact(messages, "session1", huge_system_prompt))

    assert result == messages
    assert agent.compactions_skipped_total == 1
    assert any("50%" in r.message for r in caplog.records)


def test_summarizer_failure_falls_back_to_full_history(monkeypatch, caplog):
    monkeypatch.setenv("AUREON_COMPACTION_ENABLED", "1")
    agent = _make_agent()
    agent.model = "minimax-m2.5:cloud"

    async def broken_summarize(self, messages):
        raise RuntimeError("boom")

    monkeypatch.setattr("compaction.summarizer.Summarizer.summarize", broken_summarize)

    messages = _long_history()
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(agent._maybe_compact(messages, "session1", "system prompt"))

    assert result == messages
    assert agent.compactions_skipped_total == 1
    assert any("compaction failed" in r.message for r in caplog.records)
