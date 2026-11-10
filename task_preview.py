"""Standalone activity previews, separate from participant study sessions."""
from copy import deepcopy

import streamlit as st

from activity import enter_task
from content_registry import load_activity, validate_activity
from study_flow import GROUPS, initial_activity_state


def preview_activity(activity, task_index=None):
    activity = deepcopy(activity)
    validate_activity(activity)
    state = initial_activity_state()
    if task_index is not None:
        if not 0 <= task_index < len(activity["tasks"]):
            raise ValueError("Unbekannter Abschnitt")
        activity["tasks"] = [activity["tasks"][task_index]]
        state["started"] = True
        enter_task(state, activity["tasks"][0])
    return activity, state


def render_preview_picker(store):
    st.title("Einzelne Aktivitäten und Chats testen")
    st.caption("Frische Chats ohne Anmeldung oder Fragebögen. Vorschauen werden separat gespeichert.")
    activities = {}
    for activity_id in dict.fromkeys(item for group in GROUPS.values() for item in group):
        try:
            activity = load_activity(activity_id)
            validate_activity(activity)
            activities[activity_id] = activity
        except (OSError, ValueError):
            continue
    if not activities:
        st.info("Noch keine vollständigen Aktivitäten verfügbar.")
        st.stop()
    activity_id = st.selectbox(
        "Aktivität", list(activities), key="preview_activity",
        format_func=lambda key: f"{activities[key]['role']} – {activities[key]['activity_name']}",
    )
    activity = activities[activity_id]
    selection = st.selectbox(
        "Startpunkt", [-1, *range(len(activity["tasks"]))],
        key=f"preview_task_{activity_id}",
        format_func=lambda index: "Gesamte Aktivität" if index == -1 else
        f"{index + 1}. {activity['tasks'][index]['task_title']}",
    )
    st.caption("Ein einzelner Abschnitt enthält keinen vorherigen Chatverlauf. Seine Informationen bleiben verfügbar.")
    if st.button("Chat starten", key="preview_start", type="primary"):
        content, state = preview_activity(activity, None if selection == -1 else selection)
        st.query_params["session"] = store.create(content, state)
        st.rerun()
    st.stop()
