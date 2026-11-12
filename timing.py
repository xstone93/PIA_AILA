"""Message timestamps and console-only latency diagnostics."""
from contextlib import contextmanager
from datetime import datetime, timezone
from time import perf_counter
from zoneinfo import ZoneInfo

from streamlit.logger import get_logger


logger = get_logger("minimal_chat.timing")


def utc_timestamp():
    """Capture message creation time once; persist this value with the message."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def message_time(timestamp):
    """Display stored times in Vienna; never invent times for legacy messages."""
    try:
        instant = datetime.fromisoformat(timestamp)
        if instant.tzinfo is None:
            raise ValueError("Timestamp has no timezone")
    except (ValueError, TypeError):
        return "Zeitstempel nicht verfügbar"
    return instant.astimezone(ZoneInfo("Europe/Vienna")).strftime("%d.%m.%Y %H:%M:%S %Z")


@contextmanager
def measure(operation):
    started = perf_counter()
    outcome = "ok"
    try:
        yield
    except Exception as error:
        outcome = type(error).__name__
        raise
    finally:
        logger.info("%s duration=%.3fs outcome=%s", operation, perf_counter() - started, outcome)
