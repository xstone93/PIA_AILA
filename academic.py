import requests
import streamlit as st

from timing import measure


# MODEL = "academicai:gpt-5-mini"
MODEL = "academicai:gemini-3.1-flash-lite"
URL = "https://it-u-api.academic-ai.at/api/v1/llm/chat"


class AcademicAIResponseError(ValueError):
    """A service response that cannot be displayed as an assistant message."""


def error_message(error: Exception) -> str:
    """Explain failures without exposing credentials, prompts, or response bodies."""
    if isinstance(error, AcademicAIResponseError):
        return str(error)
    if isinstance(error, requests.Timeout):
        return "AcademicAI hat innerhalb von 120 Sekunden nicht geantwortet. Bitte versuche es erneut."
    if isinstance(error, requests.HTTPError):
        status = error.response.status_code if error.response is not None else None
        if status in (401, 403):
            return f"AcademicAI hat den Zugriff abgelehnt (HTTP {status}). Bitte prüfe die Zugangsdaten und Berechtigungen."
        if status == 429:
            return "AcademicAI meldet ein Anfragelimit (HTTP 429). Bitte warte kurz und versuche es erneut."
        if status is not None:
            return f"AcademicAI hat die Anfrage mit HTTP {status} abgelehnt. Die Nachricht wurde nicht gespeichert."
        return "AcademicAI hat die Anfrage abgelehnt. Bitte versuche es erneut."
    if isinstance(error, requests.RequestException):
        return "Die Verbindung zu AcademicAI ist fehlgeschlagen. Bitte versuche es erneut."
    if isinstance(error, (KeyError, FileNotFoundError)):
        return "Die AcademicAI-Zugangsdaten fehlen. Bitte prüfe die secrets.toml."
    return "Die Antwort von AcademicAI konnte nicht verarbeitet werden. Bitte versuche es erneut."


def reply(
    messages: list[dict[str, str]],
    system_prompt: str = "",
    model_id: str = MODEL,
) -> str:    # AcademicAI accepts only user/assistant roles. Add instructions to a copy
    # of the latest user turn, keeping them out of the visible history.
    # Scripted no_wait entries are separate UI blocks within the same turn.
    # Send one message per speaker turn, without mutating the display history.
    api_messages: list[dict[str, str]] = []
    for message in messages:
        if api_messages and api_messages[-1]["role"] == message["role"]:
            api_messages[-1]["content"] += "\n\n" + message["content"]
        else:
            api_messages.append({"role": message["role"], "content": message["content"]})
    if system_prompt:
        for message in reversed(api_messages):
            if message["role"] == "user":
                message["content"] = f"[Instructions: {system_prompt}]\n\n{message['content']}"
                break
    with measure("academicai_request"):
        response = requests.post(
            URL,
            headers={
                "X-Client-ID": st.secrets["ACADEMIC_AI_CLIENT_ID"],
                "X-Client-Secret": st.secrets["ACADEMIC_AI_CLIENT_SECRET"],
            },
            json={"model": model_id.partition(":")[2], "messages": api_messages},
            timeout=120,
        )
        response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as error:
        raise AcademicAIResponseError("AcademicAI hat keine gültige JSON-Antwort geliefert.") from error
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or "content" not in data:
        raise AcademicAIResponseError("In der AcademicAI-Antwort fehlt das erwartete Feld data.content.")
    content = data["content"]
    if content is None or (isinstance(content, str) and not content.strip()):
        raise AcademicAIResponseError(
            "AcademicAI hat eine leere Antwort geliefert. Bitte sende deine Nachricht erneut."
        )
    if not isinstance(content, str):
        raise AcademicAIResponseError("AcademicAI hat ein unerwartetes Antwortformat geliefert (data.content ist kein Text).")
    return content
