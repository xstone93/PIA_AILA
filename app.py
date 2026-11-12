from copy import deepcopy
from itertools import groupby
import sqlite3

import requests
import streamlit as st

from academic import error_message
from guardrail import guarded_reply as reply

from activity import (
    advance, finish_reply, render_markdown,
    render_message, system_prompt, render_intro, enter_task, start_conversation,
)
from session_store import SessionConflict, SessionStore
from presentation import page_style, celebrate, scroll_to_latest, control_sidebar, render_task_progress
from timing import measure, utc_timestamp
from content_registry import activity_base, markdown_text
from study_flow import load_study, initial_study_state, save_activity_progress
from study_ui import render_study
import session_store
from task_preview import render_preview_picker
from chat_export import render_chat_download
from completion import step_complete
from diagnostics import diagnostic_scope


st.set_page_config(page_title="Learn Computational Thinking", layout="wide",
                   initial_sidebar_state="collapsed" if "sidebar_task" not in st.session_state else None)
preview_mode = st.query_params.get("preview") == "1"

try:
    store = SessionStore(session_store.DB_PATH.with_name("preview_sessions.sqlite3")) if preview_mode else SessionStore()
    session_id = st.query_params.get("session")
    if preview_mode:
        st.caption("Vorschaumodus – keine Studiensitzung")
        if session_id and st.button("Andere Aufgabe auswählen", key="preview_reset"):
            del st.query_params["session"]
            st.rerun()
        if not session_id:
            render_preview_picker(store)
    if not session_id:
        session_id = store.create(load_study(), initial_study_state())
        st.query_params["session"] = session_id
    # Read durable state on every rerun, including changes from another tab.
    activity, state, revision = store.load(session_id)
except (ValueError, LookupError):
    st.error("Diese Sitzung wurde nicht gefunden. Bitte verwende deinen gespeicherten Link.")
    st.stop()
except (OSError, sqlite3.Error):
    st.error("Der Sitzungsspeicher ist momentan nicht erreichbar. Bitte versuche es erneut.")
    st.stop()

snapshot = activity if activity.get("kind") == "study" else None
study_state = state if snapshot else None


def save_session(updated):
    try:
        with measure("session_save"):
            store.save(session_id, updated, revision)
    except SessionConflict:
        st.error("Die Sitzung wurde in einem anderen Fenster geändert. Bitte lade die Seite neu.")
        st.stop()
    except (OSError, sqlite3.Error, ValueError):
        st.error("Der Fortschritt konnte nicht gespeichert werden. Bitte lade die Seite neu und versuche es erneut.")
        st.stop()


if snapshot:
    page_style(intro=study_state["phase"] != "activity")
    activity, state = render_study(snapshot, study_state, save_session)

base_path = activity_base(activity)
# Older sessions already containing task messages must not replay them.
state.setdefault("conversation_started", state["next_message"] > 0)
state.setdefault("completed", False)
state.setdefault("intro_page", 0)
state.setdefault("reviewing_intro", False)
if state["started"] and "task_markers" not in state:
    state["task_markers"] = [{
        "message_index": state["task_start"],
        "task_title": activity["tasks"][state["task_index"]]["task_title"],
    }]
st.session_state.activity_state = state


def save_progress(updated_state):
    updated = save_activity_progress(snapshot, study_state, updated_state) if snapshot else updated_state
    save_session(updated)
    st.session_state.activity_state = updated_state


def start_activity():
    updated = deepcopy(state)
    updated["started"] = True
    enter_task(updated, activity["tasks"][0])
    save_progress(updated)


def next_task():
    if not can_continue or not has_next_task or state["completed"]:
        return
    if st.session_state.get("confirm_next_task") != (session_id, state["task_index"], revision):
        return
    updated = deepcopy(state)
    updated["task_index"] += 1
    enter_task(updated, activity["tasks"][updated["task_index"]])
    save_progress(updated)
    st.session_state.pop("confirm_next_task", None)


def request_next_task():
    if not can_continue or not has_next_task or state["completed"]:
        return
    st.session_state.confirm_next_task = (session_id, state["task_index"], revision)


def cancel_next_task():
    st.session_state.pop("confirm_next_task", None)


if not state["started"]:
    page_style(intro=True)
    try:
        intro = markdown_text(base_path, activity["intro_sequence"])
    except (OSError, UnicodeError, ValueError) as error:
        st.error(f"Die Einführung konnte nicht gelesen werden: {error}")
        st.stop()
    render_markdown(intro, base_path)
    st.caption("Dein Fortschritt wird automatisch gespeichert. Speichere diesen Seitenlink, um später weiterzumachen.")
    st.button("Weiter", key="start_activity", on_click=start_activity)
    st.stop()

task = activity["tasks"][state["task_index"]]
intro_files = task.get("intro_sequence", [])
# Keep the introductory instructions accessible during the welcome conversation.
if not intro_files and state["task_index"] == 0 and not activity.get("sidebar_reference"):
    intro_files = [activity["intro_sequence"]]
conversation = task.get("conversation", [])
intro_only = not conversation
has_next_task = state["task_index"] + 1 < len(activity["tasks"])
script_finished = state["next_message"] == len(conversation)
can_continue = intro_only or state["action"] == "continue" or (script_finished and (
    state.get("answered", False) if activity["role"] == "AILA" else state.get("completion_verified", False)
))
intro_pending = bool(intro_files) and not state["conversation_started"] and not state["completed"]
page_style()
sidebar_task = (session_id, activity.get("activity_id"), state["task_index"])
if st.session_state.get("sidebar_task") != sidebar_task:
    st.session_state.sidebar_task = sidebar_task
    st.session_state.sidebar_command = "open" if intro_pending else "close"


def finish_activity():
    if not can_continue or has_next_task or state["completed"]:
        return
    updated = deepcopy(state)
    updated.update(completed=True, reviewing_intro=False)
    save_progress(updated)
    # This flag is deliberately not persisted. Set it only after a successful save.
    st.session_state.celebrate_completion = session_id if not snapshot else None

def navigate_intro(page):
    updated = deepcopy(state)
    updated["intro_page"] = max(0, min(page, len(intro_files) - 1))
    save_progress(updated)

def open_intro():
    st.session_state.sidebar_command = "toggle"


def close_intro():
    st.session_state.sidebar_command = "close"


def confirm_intro():
    # Recheck all files before committing, including after a browser rerun.
    try:
        for filename in intro_files:
            markdown_text(base_path, filename)
    except (OSError, UnicodeError, ValueError):
        st.error("Die Information konnte nicht gelesen werden. Bitte versuche es erneut.")
        st.stop()
    if intro_only:
        if has_next_task:
            request_next_task()
            return
        else:
            finish_activity()
    else:
        updated = deepcopy(state)
        start_conversation(updated, task)
        save_progress(updated)
    st.session_state.sidebar_command = "close"


def render_task_intro():
    st.subheader(task["task_title"])
    page = state["intro_page"]
    readable = True
    for filename in intro_files:
        try:
            text = markdown_text(base_path, filename)
            if filename == intro_files[page]:
                current_text = text
        except (OSError, UnicodeError, ValueError):
            st.error(f"Die Information '{filename}' konnte nicht gelesen werden.")
            readable = False
    if readable:
        render_intro(current_text, base_path)
    st.caption(f"Seite {page + 1} von {len(intro_files)}")
    back, forward = st.columns(2)
    with back:
        st.button("Zurück", key="intro_back", disabled=page == 0,
                  on_click=navigate_intro, args=(page - 1,))
    with forward:
        if page < len(intro_files) - 1:
            st.button("Weiter", key="intro_next", on_click=navigate_intro, args=(page + 1,))
        elif not state["conversation_started"] and not state["completed"]:
            label = ("Weiter" if has_next_task else "Fertig") if intro_only else "Gespräch starten"
            st.button(label, key="confirm_intro", disabled=not readable, on_click=confirm_intro)
    st.button("Schließen", key="close_intro", on_click=close_intro)


if intro_files:
    with st.sidebar:
        render_task_intro()
elif activity.get("sidebar_reference"):
    with st.sidebar:
        render_intro(markdown_text(base_path, activity["sidebar_reference"]), base_path)
        st.button("Schließen", key="close_intro", on_click=close_intro)

visible_messages = state["messages"]


def render_chat_messages(messages):
    for role, messages_in_turn in groupby(messages, key=lambda message: message["role"]):
        with st.chat_message(role):
            with st.container(gap="medium"):
                for message in messages_in_turn:
                    with st.container(gap=None):
                        render_message(message, base_path)


position = 0
for marker in state.get("task_markers", []):
    boundary = marker["message_index"]
    render_chat_messages(visible_messages[position:boundary])
    st.subheader(marker["task_title"])
    position = boundary
render_chat_messages(visible_messages[position:])

if state["completed"]:
    st.success("Fertig!")
if st.session_state.pop("celebrate_completion", None) == session_id and state["completed"]:
    celebrate()

completion_notice = st.session_state.get("completion_notice") if activity["role"] == "PIA" else None
if completion_notice and completion_notice[0] == session_id:
    st.warning(
        "Deine Nachricht und die Antwort wurden gespeichert. Die automatische "
        "Abschlussprüfung ist technisch fehlgeschlagen; der Gesprächsschritt bleibt offen. "
        "Dies ist keine Bewertung deiner Antwort. Bitte versuche es mit einer kurzen Rückmeldung erneut. "
        f"Fehlerreferenz: {completion_notice[1]}"
    )
if activity["role"] == "AILA" and not intro_pending and not state["completed"]:
    if can_continue:
        st.caption("Du entscheidest als Tutor:in, wann ihr diesen Abschnitt ausreichend besprochen habt. "
                   + ("Dann kannst du „Weiter zum nächsten Thema“ wählen." if has_next_task else "Dann kannst du „Fertig“ wählen."))
    elif state.get("conversation_started"):
        st.caption("Beginne das Gespräch mit AILA. Danach entscheidest du, wann ihr weitergeht. "
                   "Die Aufgaben findest du unter „Information“.")

prompt = None
with st.container(key="chat_dock"):
    render_task_progress(activity, state)
    with st.container(horizontal=True):
        render_chat_download(activity, state, participant_code=study_state.get("participant_code") if snapshot else None)
        if intro_files or activity.get("sidebar_reference"):
            st.button("Information", icon="📖", key="open_intro", on_click=open_intro)
        if not intro_pending and not state["completed"] and can_continue:
            if has_next_task:
                st.button("⏩ Weiter zum nächsten Thema", key="next_task", on_click=request_next_task)
            else:
                st.button("Fertig", key="finish_activity", on_click=finish_activity)
    confirming_next = st.session_state.get("confirm_next_task") == (session_id, state["task_index"], revision)
    if confirming_next:
        st.write(f"Hast du diesen Abschnitt mit {activity['role']} abgeschlossen und möchtest zum nächsten Thema gelangen?")
        with st.container(horizontal=True):
            st.button("Ja, weiter", key="confirm_next_task_yes", type="primary", on_click=next_task)
            st.button("Nein, hier bleiben", key="confirm_next_task_no", on_click=cancel_next_task)
    if not confirming_next and not intro_pending and not state["completed"] and not intro_only and state["action"] != "continue":
        prompt = st.chat_input("Nachricht eingeben...")

if prompt:
    st.session_state.pop("completion_notice", None)
    user_message = {"role": "user", "content": prompt, "timestamp": utc_timestamp()}
    messages = state["messages"] + [user_message]
    model_messages = [{"role": message["role"], "content": message["content"]} for message in messages]
    with st.chat_message("user"):
        render_message(user_message, base_path)
    scroll_to_latest()
    try:
        with st.spinner(f"{activity['role']} denkt nach …", show_time=True):
            with measure("reply_total"), diagnostic_scope(
                activity_id=activity.get("activity_id"), task_index=state["task_index"],
                task_title=task["task_title"], step=state["next_message"], role=activity["role"],
                step_name=conversation[state["next_message"] - 1].get("step_name") if state["next_message"] else None,
            ) as diagnostic:
                answer = reply(model_messages, system_prompt(activity, task, state["next_message"]), role=activity["role"])
                agent_message = {"role": "assistant", "content": answer, "timestamp": utc_timestamp()}
                complete = activity["role"] == "AILA" or state.get("completion_verified", False) or step_complete(
                    model_messages[state.get("step_start", state["task_start"]):],
                    answer, system_prompt(activity, task, state["next_message"]), activity["role"],
                )
    except (requests.RequestException, KeyError, ValueError, TypeError, FileNotFoundError) as error:
        st.error(error_message(error))
    else:
        updated = deepcopy(state)
        updated["messages"] = messages + [agent_message]
        finish_reply(updated, task, activity["role"], complete)
        save_progress(updated)
        if diagnostic.get("completion_error"):
            st.session_state.completion_notice = (session_id, diagnostic["completion_error"])
        st.session_state.scroll_to_latest = session_id
        st.rerun()

if st.session_state.pop("scroll_to_latest", None) == session_id:
    scroll_to_latest()

sidebar_command = st.session_state.pop("sidebar_command", None)
if sidebar_command:
    control_sidebar(sidebar_command)
