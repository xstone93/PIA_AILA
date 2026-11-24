"""Assess PIA learner answers; AILA section completion belongs to the human tutor."""
import json
import re

import requests
from streamlit.logger import get_logger

from academic import reply
from guardrail import GUARDRAIL_MODEL
from diagnostics import completion_failed, record, reference

from pia_prompts import ASSESSMENT_RULES

logger = get_logger("minimal_chat.completion")
ASSESSMENT_VERSION = 2  # Earlier ledgers could include PIA behavior as learner work.


def validate_assessment(decision, messages, previous):
    """Validate evidence and keep a stable rubric within one PIA question."""
    if not isinstance(decision, dict) or not isinstance(decision.get("reason"), str):
        raise ValueError("Invalid assessment")
    criteria = decision.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("Missing criteria")
    old = {c["id"]: c for c in previous.get("criteria", [])}
    seen = set()
    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise ValueError("Invalid criterion")
        key = criterion.get("id")
        if not isinstance(key, str) or not key.strip() or key in seen:
            raise ValueError("Invalid criterion ID")
        seen.add(key)
        if not isinstance(criterion.get("requirement"), str) or not criterion["requirement"].strip():
            raise ValueError("Invalid requirement")
        if criterion.get("status") not in ("met", "missing", "incorrect"):
            raise ValueError("Invalid criterion status")
        evidence = criterion.get("evidence")
        if not isinstance(evidence, list) or any(
            type(index) is not int or not 0 <= index < len(messages)
            or messages[index]["role"] != "user" for index in evidence
        ):
            raise ValueError("Invalid learner evidence")
        if criterion["status"] != "missing" and not evidence:
            raise ValueError("Missing learner evidence")
        if key in old:
            before = old[key]
            if criterion["requirement"] != before["requirement"]:
                raise ValueError("Changed requirement")
            if before["status"] == "met" and criterion["status"] != "met":
                # A later explicit contradiction may reopen a criterion. Mere
                # omission or repeating an older error cannot erase progress.
                if criterion["status"] != "incorrect" or max(evidence, default=-1) <= max(before["evidence"]):
                    criterion.update(status="met", evidence=before["evidence"])
    if old and seen != set(old):
        raise ValueError("Changed criterion set")
    decision["step_complete"] = all(c["status"] == "met" for c in criteria)
    return decision


def step_complete(messages, context, role, assessment=None):
    reference_id = reference()
    latest = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    if re.fullmatch(r"\s*(?:weiter|continue|next|überspringen|skip|(?:okay[,!]?\s*)?dann\s+(?:machen|tun)\s+wir\s+weiter|(?:ja[,!]?\s*)?lass\s+uns\s+weitermachen)[\s.!?]*", latest, re.I):
        if assessment is not None:
            assessment.update(assessment.get("previous", {}))
            assessment.update(step_complete=False, reason="Navigation request only; preserve accepted parts and address one unresolved criterion.")
        logger.info("step_incomplete role=%s reason=navigation_only", role)
        return False
    logger.info("completion_check_started role=%s", role)
    raw = None
    try:
        raw = reply([{"role": "user", "content": json.dumps({
            "role": role, "current_step_context": context,
            "conversation": messages,
            "learner_evidence": [{"message_index": index, "content": message["content"]}
                                 for index, message in enumerate(messages) if message["role"] == "user"],
            "previous_assessment": (assessment or {}).get("previous", {}),
        }, ensure_ascii=False)}], ASSESSMENT_RULES, model_id=GUARDRAIL_MODEL)
        decision = validate_assessment(json.loads(raw), messages, (assessment or {}).get("previous", {}))
    except (ValueError, TypeError, requests.RequestException, KeyError):
        reason = "completion_service" if raw is None else "completion_decision"
        completion_failed(reference_id)
        record("completion_check_failed", reference_id, role=role, reason=reason,
               conversation=messages, validator_output=raw,
               current_step_context=context)
        logger.warning("completion_error reference=%s reason=%s", reference_id, reason)
        logger.warning("completion_check_failed role=%s", role)
        return False
    result = decision["step_complete"]
    if assessment is not None:
        assessment.update(decision)
    record("completion_checked", reference_id, role=role, step_complete=result,
           reason=decision.get("reason", ""), conversation=messages,
           current_step_context=context)
    logger.info("completion_checked role=%s step_complete=%s", role, result)
    return result
