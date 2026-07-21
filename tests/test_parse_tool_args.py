import unittest

from agent_runtime import _parse_tool_args


class TestParseToolArgs(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_parse_tool_args(""), {})
        self.assertEqual(_parse_tool_args(None), {})
        self.assertEqual(_parse_tool_args("   "), {})

    def test_plain_object(self):
        self.assertEqual(_parse_tool_args('{"a": 1}'), {"a": 1})

    def test_trailing_prose_no_fence(self):
        # gemma sometimes appends a sentence after the JSON -> "Extra data" otherwise
        raw = '{"query": "invoice newer_than:7d"} and then I will read each message.'
        self.assertEqual(_parse_tool_args(raw), {"query": "invoice newer_than:7d"})

    def test_code_fence(self):
        raw = '```json\n{"query": "x", "limit": 5}\n```'
        self.assertEqual(_parse_tool_args(raw), {"query": "x", "limit": 5})

    def test_array_args(self):
        raw = '["a", "b"] trailing note'
        self.assertEqual(_parse_tool_args(raw), ["a", "b"])

    def test_nested_object_with_trailing(self):
        raw = '{"outer": {"inner": "v"}, "n": 2} done.'
        self.assertEqual(_parse_tool_args(raw), {"outer": {"inner": "v"}, "n": 2})

    def test_string_containing_brace(self):
        # ensure we don't cut off early on a brace inside a string
        raw = '{"q": "a } b"} extra'
        self.assertEqual(_parse_tool_args(raw), {"q": "a } b"})


if __name__ == "__main__":
    unittest.main()
