"""Model-aware compaction threshold: how much history a session can hold before
the old turns need summarizing, given the active model's context window and the
current system prompt size."""
import logging
import os

from aureon_agent.models import get_context_window
from compaction.counter import count_tokens_text

logger = logging.getLogger(__name__)

DEFAULT_RESERVED_RESPONSE_TOKENS = 4096
MAX_RECENT_VERBATIM_TOKENS = 4000


def compute_compact_threshold(model: str, system_prompt: str) -> int:
    context_window = get_context_window(model)
    reserved = int(os.getenv("AUREON_RESERVED_RESPONSE_TOKENS", DEFAULT_RESERVED_RESPONSE_TOKENS))
    system_prompt_tokens = count_tokens_text(system_prompt)

    if system_prompt_tokens > 0.5 * context_window:
        logger.error(
            "system prompt (%d tokens) exceeds 50%% of %s's context window (%d) — "
            "no room for history, skipping compaction",
            system_prompt_tokens, model, context_window,
        )
        return 0

    return context_window - reserved - system_prompt_tokens


def compute_recent_verbatim_size(compact_threshold: int) -> int:
    return min(MAX_RECENT_VERBATIM_TOKENS, int(compact_threshold * 0.2))
