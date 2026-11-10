"""Console-only latency diagnostics; never log prompts or credentials."""
from contextlib import contextmanager
from time import perf_counter

from streamlit.logger import get_logger


logger = get_logger("minimal_chat.timing")


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
