"""Schedule parsing and next-run calculation for cron jobs.

Supports three schedule types:
  - cron:     5-field Vixie cron expression (via croniter)
  - interval: Nm / Nh / Nd shorthand
  - at:       ISO 8601 one-shot timestamp
"""
import logging
import random
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_INTERVAL_RE = re.compile(r"^(\d+)([mhd])$")

_INTERVAL_MULTIPLIERS = {
    "m": 60,
    "h": 3600,
    "d": 86400,
}


def detect_schedule_type(schedule: str) -> str:
    """Detect whether a schedule string is 'cron', 'interval', or 'at'.

    Rules:
      - Contains 'T' and ('-' or ':'): 'at' (ISO timestamp)
      - Matches ^\\d+[mhd]$: 'interval'
      - Otherwise: 'cron' (5-field cron expression)
    """
    s = schedule.strip()
    if "T" in s and ("-" in s or ":" in s):
        return "at"
    if _INTERVAL_RE.match(s):
        return "interval"
    return "cron"


def parse_interval(s: str) -> int:
    """Parse an interval string like '30m', '2h', '1d' into seconds.

    Raises ValueError on invalid format.
    """
    m = _INTERVAL_RE.match(s.strip())
    if not m:
        raise ValueError(f"Invalid interval format: {s!r} (expected Nm, Nh, or Nd)")
    count = int(m.group(1))
    unit = m.group(2)
    if count <= 0:
        raise ValueError(f"Interval count must be positive: {s!r}")
    return count * _INTERVAL_MULTIPLIERS[unit]


def parse_iso_timestamp(s: str, tz_name: str = "UTC") -> float:
    """Parse an ISO 8601 timestamp string into a Unix timestamp.

    If no timezone info in the string, uses tz_name (default UTC).
    Raises ValueError on invalid format.
    """
    s = s.strip()
    try:
        # Try parsing with timezone info first
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            # Apply the specified timezone
            import zoneinfo
            tzinfo = zoneinfo.ZoneInfo(tz_name)
            dt = dt.replace(tzinfo=tzinfo)
        return dt.timestamp()
    except (ValueError, KeyError) as e:
        raise ValueError(f"Invalid ISO timestamp: {s!r} — {e}") from e


def calc_next_run(schedule: str, schedule_type: str, from_time: float,
                  tz: str = "UTC", exact: bool = False) -> float:
    """Calculate the next run timestamp for a job.

    Args:
        schedule:      The schedule string (cron expr, interval, or ISO timestamp)
        schedule_type: One of 'cron', 'interval', 'at'
        from_time:     Base time (Unix timestamp) to calculate from
        tz:            Timezone name for cron expressions (default UTC)
        exact:         If True, disable top-of-hour staggering

    Returns:
        Next run time as Unix timestamp.
    """
    if schedule_type == "at":
        return parse_iso_timestamp(schedule, tz)

    if schedule_type == "interval":
        interval_sec = parse_interval(schedule)
        return from_time + interval_sec

    if schedule_type == "cron":
        return _calc_cron_next(schedule, from_time, tz, exact)

    raise ValueError(f"Unknown schedule_type: {schedule_type!r}")


def _calc_cron_next(expression: str, from_time: float,
                    tz: str = "UTC", exact: bool = False) -> float:
    """Calculate next run for a cron expression using croniter."""
    from croniter import croniter
    import zoneinfo

    tzinfo = zoneinfo.ZoneInfo(tz)
    base_dt = datetime.fromtimestamp(from_time, tz=tzinfo)
    cron = croniter(expression, base_dt)
    next_dt = cron.get_next(datetime)
    next_ts = next_dt.timestamp()

    # Top-of-hour staggering: if minute field is 0 and exact is False,
    # add random 0-300 seconds (0-5 min) to reduce load spikes
    if not exact:
        fields = expression.strip().split()
        if len(fields) >= 1 and fields[0] == "0":
            stagger = random.randint(0, 300)
            if stagger > 0:
                logger.info("cron stagger: %s staggered by %ds", expression, stagger)
                next_ts += stagger

    return next_ts
