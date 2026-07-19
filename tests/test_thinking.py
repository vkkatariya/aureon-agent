import sys
import os
import unittest
from unittest.mock import patch

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_runtime import AgentRuntime

class TestThinkingMode(unittest.IsolatedAsyncioTestCase):

    async def test_thinking_field_claude(self):
        agent = AgentRuntime(base_url="http://mock", api_key="test", model="claude-3-5-sonnet", skill_loader=None, workspace_dir="/tmp", memory=None, thinking=True, thinking_budget=1024)
        field = agent._thinking_field()
        self.assertEqual(field, {"thinking": {"type": "enabled", "budget_tokens": 1024}})

    async def test_thinking_field_deepseek(self):
        agent = AgentRuntime(base_url="http://mock", api_key="test", model="deepseek-r1", skill_loader=None, workspace_dir="/tmp", memory=None, thinking=True, thinking_budget=1024)
        field = agent._thinking_field()
        self.assertEqual(field, {"reasoning_effort": "high"})

    async def test_reasoning_capture(self):
        agent = AgentRuntime(base_url="http://mock", api_key="test", model="claude-3", skill_loader=None, workspace_dir="/tmp", memory=None, thinking=True)
        
        thinking_tokens = []
        text_tokens = []
        
        async def mock_on_thinking(token):
            thinking_tokens.append(token)
            
        async def mock_on_token(token):
            text_tokens.append(token)

        class MockStream:
            async def aiter_lines(self):
                yield 'data: {"choices":[{"delta":{"reasoning_content":"thought1"}}]}'
                yield 'data: {"choices":[{"delta":{"thinking":"thought2"}}]}'
                yield 'data: {"choices":[{"delta":{"content":"answer1"}}]}'
                yield 'data: [DONE]'
                
            async def __aenter__(self):
                self.status_code = 200
                return self
                
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class MockClient:
            def stream(self, method, url, headers=None, json=None):
                return MockStream()
                
            async def __aenter__(self):
                return self
                
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        with patch("httpx.AsyncClient", return_value=MockClient()):
            res = await agent._stream("http://mock", "test", {}, mock_on_token, on_thinking=mock_on_thinking)
            
            self.assertEqual(res["text"], "answer1")
            self.assertEqual(thinking_tokens, ["thought1", "thought2"])
            self.assertEqual(text_tokens, ["answer1"])

    async def test_call_llm_body_injection(self):
        agent = AgentRuntime(base_url="http://mock", api_key="test", model="claude-3-5-sonnet", skill_loader=None, workspace_dir="/tmp", memory=None, thinking=True, thinking_budget=1024)
        
        captured_body = None
        
        async def mock_stream(base_url, api_key, body, on_token, on_thinking=None):
            nonlocal captured_body
            captured_body = body
            return {"text": "mock_response", "tool_calls": None}
            
        agent._stream = mock_stream
        
        await agent._call_llm("System", [{"role": "user", "content": "hi"}], [], None)
        
        self.assertIn("thinking", captured_body)
        self.assertEqual(captured_body["thinking"], {"type": "enabled", "budget_tokens": 1024})

if __name__ == "__main__":
    unittest.main()
