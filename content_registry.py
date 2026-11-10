"""Activity discovery and validation, independent of Streamlit."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT_ROOT = ROOT / "learning_activities"
DEFAULT_ACTIVITY = "aila_robot_and_batteries"
IMAGE = re.compile(r"(?:!\[|\[!)([^\]]*)\]\(([^)]+)\)(?:[ \t]*\{width=([1-9][0-9]*)\})?")


def local_file(base, name):
    """Only resolve content inside its configured folder."""
    base = Path(base).resolve()
    path = (base / name).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Dateipfad außerhalb des Inhaltsordners: {name}")
    if not path.is_file():
        raise ValueError(f"Datei fehlt: {path}")
    return path


def activity_file(activity_id=DEFAULT_ACTIVITY):
    for role in ("aila", "pia"):
        prefix = role + "_"
        if activity_id.startswith(prefix):
            topic = activity_id[len(prefix):]
            if topic not in ("robot_and_batteries", "cables_and_tester"):
                break
            filename = "robot-and-battery" if topic == "robot_and_batteries" else "cables-and-tester"
            return CONTENT_ROOT / role / topic / f"{filename}_{role}.json"
    raise ValueError(f"Unbekannte Aktivität: {activity_id}")


def activity_base(activity):
    # Legacy database snapshots have no identifier, but use the original content.
    return activity_file(activity.get("activity_id", DEFAULT_ACTIVITY)).parent


def load_activity(activity_id=DEFAULT_ACTIVITY):
    path = activity_file(activity_id)
    activity = json.loads(path.read_text(encoding="utf-8"))
    if activity.get("activity_id") != activity_id:
        raise ValueError(f"Aktivitätskennung passt nicht zur Datei: {path}")
    role = activity.get("role", "").lower()
    if role not in ("pia", "aila") or not activity_id.startswith(role + "_"):
        raise ValueError(f"Ungültige Rolle: {path}")
    activity["role_framework"] = local_file(CONTENT_ROOT / role, "role.md").read_text(encoding="utf-8")
    return activity


def markdown_text(base, filename):
    text = local_file(base, filename).read_text(encoding="utf-8")
    validate_images(base, text)
    return text


def validate_images(base, text):
    for match in IMAGE.finditer(text):
        local_file(base, match.group(2))


def validate_activity(activity):
    """Raise an actionable error before participants enter incomplete content."""
    if activity.get("status") != "ready":
        raise ValueError(f"Aktivität ist noch ein Entwurf: {activity.get('activity_id', '?')}")
    base = activity_base(activity)
    if not activity.get("role_framework", "").strip():
        raise ValueError("Rollenbeschreibung fehlt")
    if not isinstance(activity.get("intro_sequence"), str):
        raise ValueError("Aktivität benötigt eine Markdown-Einführung")
    markdown_text(base, activity["intro_sequence"])
    if activity.get("sidebar_reference"):
        markdown_text(base, activity["sidebar_reference"])
    if not isinstance(activity.get("tasks"), list) or not activity["tasks"]:
        raise ValueError("Aktivität benötigt mindestens einen Abschnitt")
    for task in activity["tasks"]:
        if not isinstance(task, dict) or not task.get("task_title"):
            raise ValueError("Abschnitt benötigt task_title")
        intros = task.get("intro_sequence", [])
        conversation = task.get("conversation", [])
        if not isinstance(intros, list) or not all(isinstance(name, str) for name in intros):
            raise ValueError("intro_sequence eines Abschnitts muss eine Dateiliste sein")
        if not isinstance(conversation, list):
            raise ValueError("conversation muss eine Liste sein")
        for filename in intros:
            markdown_text(base, filename)
        for message in conversation:
            if not isinstance(message, dict):
                raise ValueError("Gesprächseintrag muss ein Objekt sein")
            content = message.get("message")
            if content is not None and not isinstance(content, str):
                raise ValueError("Gesprächsnachricht muss Text sein")
            if message.get("action", "wait") not in ("wait", "continue", "no_wait"):
                raise ValueError("Unbekannte Gesprächsaktion")
            if content:
                if message.get("type") == "image" and not IMAGE.fullmatch(content):
                    local_file(base, content)
                else:
                    validate_images(base, content)
