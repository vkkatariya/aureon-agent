import logging

import tiktoken

from aureon_agent.models import get_context_window
from compaction.threshold import compute_compact_threshold, compute_recent_verbatim_size

_ENC = tiktoken.get_encoding("cl100k_base")
_BASE_IDS = _ENC.encode("The quick brown fox jumps over the lazy dog. ")


def _text_with_token_count(n):
    """Build a string whose tiktoken token count is exactly n (same encoding
    compaction.counter uses), so threshold math is exact rather than approximate."""
    ids = (_BASE_IDS * (n // len(_BASE_IDS) + 1))[:n]
    return _ENC.decode(ids)


def test_get_context_window_known_models():
    assert get_context_window("minimax-m2.5:cloud") == 32_768
    assert get_context_window("claude-sonnet-4[1m]") == 1_000_000


def test_get_context_window_unknown_model_falls_back_and_warns(caplog):
    with caplog.at_level(logging.WARNING):
        assert get_context_window("unknown-model") == 32_768
    assert any("unknown-model" in r.message for r in caplog.records)


def test_compute_compact_threshold_small_model():
    system_prompt = _text_with_token_count(2_000)
    actual_prompt_tokens = len(_ENC.encode(system_prompt))
    threshold = compute_compact_threshold("minimax-m2.5:cloud", system_prompt)
    # 32768 - 4096 (default reserved) - actual system prompt tokens
    assert threshold == 32_768 - 4096 - actual_prompt_tokens


def test_compute_compact_threshold_huge_model():
    system_prompt = _text_with_token_count(5_000)
    actual_prompt_tokens = len(_ENC.encode(system_prompt))
    threshold = compute_compact_threshold("claude-sonnet-4[1m]", system_prompt)
    # 1_000_000 - 4096 - actual system prompt tokens
    assert threshold == 1_000_000 - 4096 - actual_prompt_tokens


def test_compute_compact_threshold_system_prompt_too_big_skips(caplog):
    system_prompt = _text_with_token_count(20_000)  # > 50% of 32K window
    with caplog.at_level(logging.ERROR):
        threshold = compute_compact_threshold("minimax-m2.5:cloud", system_prompt)
    assert threshold == 0
    assert any("50%" in r.message for r in caplog.records)


def test_compute_recent_verbatim_size():
    assert compute_recent_verbatim_size(1_000_000) == 4000
    assert compute_recent_verbatim_size(20_000) == 4000
    assert compute_recent_verbatim_size(10_000) == 2000
