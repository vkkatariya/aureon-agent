"""Log redaction: Telegram bot tokens live in Bot API URLs (`/bot<id>:<secret>/`)
and must never reach the journal, whichever logger emits the URL."""
import logging
import re

_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]{20,}")


def redact(text: str) -> str:
    return _TOKEN_RE.sub("bot<redacted>", text)


class RedactTokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, ()
        return True


def install(level_for_noisy=logging.WARNING) -> None:
    """Attach the filter to every root handler and quiet httpx/httpcore."""
    f = RedactTokenFilter()
    for h in logging.getLogger().handlers:
        if not any(isinstance(x, RedactTokenFilter) for x in h.filters):
            h.addFilter(f)
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(level_for_noisy)
