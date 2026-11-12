"""Opt-in local model diagnostics, separate from ordinary application logs."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

from streamlit.logger import get_logger


DIAGNOSTICS_PATH = Path(__file__).parent / "data" / "model_diagnostics.jsonl"
_current = ContextVar("model_diagnostic_context", default=None)
logger = get_logger("minimal_chat.diagnostics")


@contextmanager
def diagnostic_scope(**metadata):
    context = {"reference": uuid4().hex[:12], **metadata}
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)


def reference():
    context = _current.get()
    return context["reference"] if context else uuid4().hex[:12]


def record(event, reference_id, **details):
    """Never put model content in normal logs, even if file writing fails."""
    if os.environ.get("AILA_DIAGNOSTICS") != "1":
        return
    context = _current.get() or {}
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(),
             **context, "reference": reference_id, "event": event, **details}
    try:
        DIAGNOSTICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DIAGNOSTICS_PATH.open("a", encoding="utf-8") as output:
            output.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("diagnostic_write_failed reference=%s", reference_id)


def completion_failed(reference_id):
    context = _current.get()
    if context is not None:
        context["completion_error"] = reference_id
