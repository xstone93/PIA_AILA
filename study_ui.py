"""Study pages surrounding the shared activity UI."""
from copy import deepcopy
import streamlit as st

from activity import render_markdown, render_message
from content_registry import activity_base
from chat_export import render_chat_download
from study_flow import (STUDY_ROOT, enroll, readiness_errors, checkpoint_key,
                        confirm_checkpoint, current_activity_id)


def render_study(snapshot, state, save):
    """Return the active activity and progress, or stop on a study page."""
    st.caption("Speichere diesen Seitenlink, um deine Sitzung später fortzusetzen.")
    phase = state["phase"]
    if phase == "activity":
        activity_id = current_activity_id(snapshot, state)
        st.caption(f"Aktivität {state['activity_index'] + 1} von 2 · {snapshot['activities'][activity_id]['role']}")
        return snapshot["activities"][activity_id], state["activities"][activity_id]
    if phase == "welcome":
        render_markdown(snapshot["welcome"], STUDY_ROOT)
        if st.button("Weiter", key="welcome_next"):
            updated = deepcopy(state)
            updated["phase"] = "enrollment"
            save(updated)
            st.rerun()
    elif phase == "enrollment":
        st.header("Anmeldung zur Studie")
        st.write("Gruppe A: PIA Roboter und Batterien → AILA Kabel und Tester")
        st.write("Gruppe B: PIA Kabel und Tester → AILA Roboter und Batterien")
        with st.form("enrollment"):
            group = st.selectbox("Zugewiesene Gruppe", ["A", "B"], index=None, key="study_group")
            code = st.text_input("Teilnahmecode", key="participant_code")
            submitted = st.form_submit_button("Anmeldung abschließen")
        if group and readiness_errors(snapshot, group):
            st.warning("Diese Studiengruppe ist noch nicht freigegeben. Bitte wende dich an die Studienleitung.")
        if submitted:
            try:
                updated = enroll(snapshot, state, group, code)
            except ValueError as error:
                # Configuration details belong to administrators, not participants.
                if group and readiness_errors(snapshot, group):
                    st.error("Diese Studiengruppe ist noch nicht freigegeben.")
                else:
                    st.error(str(error))
            else:
                save(updated)
                st.rerun()
    elif phase in ("pre_survey", "post_survey"):
        checkpoint = snapshot["checkpoints"][checkpoint_key(snapshot, state)]
        if phase == "post_survey":
            st.success(f"Lernaktivität {state['activity_index'] + 1} abgeschlossen.")
            activity_id = current_activity_id(snapshot, state)
            render_chat_download(snapshot["activities"][activity_id], state["activities"][activity_id])
        if checkpoint["text"]:
            render_markdown(checkpoint["text"], STUDY_ROOT)
        st.link_button("Fragebogen in neuem Tab öffnen", checkpoint["survey_url"])
        confirmed = st.checkbox("Ich habe den Fragebogen ausgefüllt und bin zurückgekehrt.",
                                key=f"confirm_{state['activity_index']}_{phase}")
        if st.button("Weiter", key="survey_next", disabled=not confirmed):
            save(confirm_checkpoint(snapshot, state))
            st.rerun()
    elif phase == "completed":
        render_markdown(snapshot["completion"], STUDY_ROOT)
        for activity_id, progress in state["activities"].items():
            activity = snapshot["activities"][activity_id]
            with st.expander(f"{activity['role']} · {activity['activity_name']}"):
                render_chat_download(activity, progress, key=f"download_{activity_id}")
                for message in progress["messages"]:
                    with st.chat_message(message["role"]):
                        render_message(message, activity_base(activity))
    else:
        st.error("Unbekannter Studienstatus. Bitte wende dich an die Studienleitung.")
    st.stop()
