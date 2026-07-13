"""Context-window lookup table for compaction threshold math. Unknown models
fall back to the smallest known window (32K) rather than assuming unlimited room."""
import logging

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_WINDOW = 32_768

MODEL_CONTEXT_WINDOWS = {
    "minimax-m2.5:cloud": 32_768,
    "minimax-m3:cloud": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-sonnet-4[1m]": 1_000_000,
    "claude-opus-4": 200_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
}


def get_context_window(model: str) -> int:
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]
    logger.warning(
        "unknown model %r in MODEL_CONTEXT_WINDOWS, falling back to %d-token default",
        model, DEFAULT_CONTEXT_WINDOW,
    )
    return DEFAULT_CONTEXT_WINDOW
