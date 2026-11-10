"""Durable study transitions. No Streamlit dependencies."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit

from content_registry import load_activity, validate_activity, markdown_text

STUDY_ROOT = Path(__file__).resolve().parent / "study"
CONFIG_FILE = STUDY_ROOT / "config.json"
GROUPS = {
    "A": ["pia_robot_and_batteries", "aila_cables_and_tester"],
    "B": ["pia_cables_and_tester", "aila_robot_and_batteries"],
}


def now():
    return datetime.now(timezone.utc).isoformat()


def initial_activity_state():
    return dict(started=False, completed=False, task_index=0, next_message=0,
                action="wait", messages=[], task_start=0, answered=False)


def initial_study_state():
    return dict(phase="welcome", group=None, participant_code=None,
                activity_index=0, activities={}, checkpoints={})


def load_study():
    """Snapshot content and readiness errors without exposing drafts to participants."""
    config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    if config.get("groups") != GROUPS or not config.get("version"):
        raise ValueError("Studienkonfiguration: Gruppen oder Version ungültig")
    snapshot = {"kind": "study", "config": deepcopy(config), "activities": {}, "errors": {}}
    for key in ("welcome", "completion"):
        snapshot[key] = markdown_text(STUDY_ROOT, config[key])
    checkpoint_defs = [("pre_study", config.get("pre_study"))]
    checkpoint_defs += [(activity_id, config.get("post_activity", {}).get(activity_id))
                        for sequence in GROUPS.values() for activity_id in sequence]
    snapshot["checkpoints"] = {}
    for key, definition in checkpoint_defs:
        try:
            if not isinstance(definition, dict):
                raise ValueError(f"Fragebogen-Konfiguration fehlt: {key}")
            url = definition.get("survey_url", "")
            parsed = urlsplit(url)
            if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.username or parsed.password:
                raise ValueError(f"Fragebogen-Link fehlt oder ist ungültig: {key}")
            text = markdown_text(STUDY_ROOT, definition["markdown"]) if definition.get("markdown") else ""
            snapshot["checkpoints"][key] = {"text": text, "survey_url": url}
        except (ValueError, OSError, KeyError, TypeError) as error:
            snapshot["errors"][key] = str(error)
    for sequence in GROUPS.values():
        for activity_id in sequence:
            try:
                activity = load_activity(activity_id)
                validate_activity(activity)
                snapshot["activities"][activity_id] = activity
            except (ValueError, OSError, KeyError, TypeError) as error:
                snapshot["errors"][activity_id] = str(error)
    return snapshot


def readiness_errors(snapshot, group):
    if group not in GROUPS:
        return ["Bitte wähle Gruppe A oder B."]
    keys = ["pre_study", *snapshot["config"]["groups"][group]]
    return [snapshot["errors"][key] for key in keys if key in snapshot["errors"]]


def enroll(snapshot, state, group, participant_code):
    if state["phase"] != "enrollment" or state.get("group") is not None:
        raise ValueError("Die Anmeldung ist bereits abgeschlossen.")
    if not isinstance(participant_code, str) or not participant_code.strip():
        raise ValueError("Bitte gib deinen Teilnahmecode ein.")
    errors = readiness_errors(snapshot, group)
    if errors:
        raise ValueError("Diese Studiengruppe ist noch nicht freigegeben. " + " / ".join(errors))
    result = deepcopy(state)
    result.update(group=group, participant_code=participant_code.strip(), phase="pre_survey",
                  study_version=snapshot["config"]["version"], enrolled_at=now())
    return result


def current_activity_id(snapshot, state):
    return snapshot["config"]["groups"][state["group"]][state["activity_index"]]


def checkpoint_key(snapshot, state):
    if state["phase"] == "pre_survey":
        return "pre_study"
    if state["phase"] == "post_survey":
        return current_activity_id(snapshot, state)
    raise ValueError("Kein Fragebogen in dieser Phase")


def confirm_checkpoint(snapshot, state):
    key = checkpoint_key(snapshot, state)
    if key not in snapshot["checkpoints"]:
        raise ValueError("Fragebogen ist nicht konfiguriert")
    result = deepcopy(state)
    result["checkpoints"][key] = {"self_reported_completed_at": now(), "verification": "self_reported"}
    if state["phase"] == "post_survey":
        if state["activity_index"] == 1:
            result.update(phase="completed", completed_at=now())
            return result
        result["activity_index"] += 1
    result["phase"] = "activity"
    activity_id = current_activity_id(snapshot, result)
    result["activities"][activity_id] = initial_activity_state()
    return result


def save_activity_progress(snapshot, state, progress):
    if state["phase"] != "activity":
        raise ValueError("Keine aktive Lernaktivität")
    result = deepcopy(state)
    activity_id = current_activity_id(snapshot, state)
    result["activities"][activity_id] = deepcopy(progress)
    if progress.get("completed"):
        result["phase"] = "post_survey"
        result["activities"][activity_id]["completed_at"] = now()
    return result


if __name__ == "__main__":
    snapshot = load_study()
    for group in GROUPS:
        errors = readiness_errors(snapshot, group)
        print(f"Gruppe {group}: " + ("bereit" if not errors else "NICHT BEREIT"))
        for error in errors:
            print(f"  {error}")
    raise SystemExit(1 if snapshot["errors"] else 0)
