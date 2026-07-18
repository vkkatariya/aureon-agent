"""Tests for the Telegram /command code-block wrapping (channels/telegram.py).

The Rich tables from /sessions, /doctor, /status etc. collapse in Telegram
plain text; they must be delivered inside a MarkdownV2 fenced code block."""
from channels.telegram import (
    CODEBLOCK_CHUNK_LEN,
    _chunk_for_codeblock,
    _md_code_block,
)


def test_md_code_block_fences():
    wrapped = _md_code_block("Chat Sessions\n┏━━┓\n┃id┃\n┗━━┛")
    assert wrapped.startswith("```")
    assert wrapped.endswith("```")
    # box-drawing content preserved intact between the fences
    assert "┏━━┓" in wrapped


def test_md_code_block_escapes_backticks_and_backslashes():
    wrapped = _md_code_block("path C:\\tmp and `code`")
    body = wrapped[len("```\n"):-len("\n```")]
    assert "\\\\" in body       # backslash escaped
    assert "\\`" in body        # backtick escaped


def test_chunk_for_codeblock_splits_large_output():
    big = "x" * (CODEBLOCK_CHUNK_LEN * 2 + 10)
    chunks = _chunk_for_codeblock(big)
    assert len(chunks) == 3
    assert all(len(c) <= CODEBLOCK_CHUNK_LEN for c in chunks)


def test_chunk_for_codeblock_empty_yields_one():
    assert _chunk_for_codeblock("   ") == [""]


def test_every_chunk_independently_fenced():
    big = "line\n" * 2000
    for chunk in _chunk_for_codeblock(big):
        wrapped = _md_code_block(chunk)
        assert wrapped.startswith("```") and wrapped.endswith("```")
