"""Token counting for compaction decisions. Uses tiktoken when importable,
else a len(text)/4 heuristic — accurate enough for threshold comparisons."""
try:
    import tiktoken

    _ENCODING = tiktoken.get_encoding("cl100k_base")
except ImportError:
    _ENCODING = None


def count_tokens_text(text: str) -> int:
    if not text:
        return 0
    if _ENCODING:
        return len(_ENCODING.encode(text))
    return len(text) // 4


def count_tokens_messages(messages: list) -> int:
    return sum(count_tokens_text(m.get("content") or "") for m in messages)


def needs_compaction(history_tokens: int, threshold: int) -> bool:
    return history_tokens > threshold
