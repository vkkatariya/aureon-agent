"""Calls the LLM to compress old session turns into a short summary. Never
strands the conversation: on timeout or API failure, falls back to a truncated
transcript instead of raising."""
import logging

import httpx

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM_PROMPT = (
    "You are summarizing a conversation between a user and an AI agent. "
    "Produce a 200-word summary that preserves: facts learned, decisions made, "
    "file paths discussed, errors encountered, todos stated. Drop: greetings, "
    "hedging, redundant context. The next agent reading this summary needs to "
    "continue the conversation seamlessly. Write in third person "
    "('The user asked...', 'The agent responded...')."
)

MAX_OUTPUT_TOKENS = 300
TIMEOUT_SECONDS = 30
DEGRADED_FALLBACK_CHARS = 500


class Summarizer:
    def __init__(self, base_url, api_key=None, model="minimax-m2.5:cloud"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def summarize(self, messages: list) -> str:
        transcript = "\n".join(f"{m.get('role')}: {m.get('content') or ''}" for m in messages)

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
            "max_tokens": MAX_OUTPUT_TOKENS,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                res = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=body)
                res.raise_for_status()
                data = res.json()
                return data["choices"][0]["message"]["content"].strip()
        except (httpx.TimeoutException, httpx.HTTPError, KeyError, IndexError) as e:
            logger.warning("compaction summarization failed (%s), falling back to truncated transcript", e)
            return transcript[:DEGRADED_FALLBACK_CHARS]
