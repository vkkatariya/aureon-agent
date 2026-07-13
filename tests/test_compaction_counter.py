from compaction.counter import count_tokens_messages, count_tokens_text, needs_compaction


def test_count_tokens_text_matches_tiktoken_within_20_percent():
    import tiktoken

    sample = "The quick brown fox jumps over the lazy dog. " * 50
    exact = len(tiktoken.get_encoding("cl100k_base").encode(sample))
    counted = count_tokens_text(sample)
    assert abs(counted - exact) <= exact * 0.2


def test_count_tokens_text_empty():
    assert count_tokens_text("") == 0
    assert count_tokens_text(None) == 0


def test_count_tokens_messages_sums_content():
    messages = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "world"}]
    assert count_tokens_messages(messages) == count_tokens_text("hello") + count_tokens_text("world")


def test_needs_compaction():
    assert needs_compaction(10_000, 26_000) is False
    assert needs_compaction(30_000, 26_000) is True
