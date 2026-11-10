"""Export only the visible transcript, never activity instructions or session IDs."""
from datetime import datetime, timezone
import re

import streamlit as st

from content_registry import IMAGE


def chat_markdown(activity, state):
    role = activity.get("role", "Assistant")
    lines = [f"# {activity.get('activity_name', 'Chat')}", "",
             f"Agent: {role}", "",
             f"Exportiert (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}", "",
             "Abbildungen werden als Textverweise exportiert.", ""]
    markers = {}
    for marker in state.get("task_markers", []):
        markers.setdefault(marker["message_index"], []).append(marker.get("task_title", ""))
    messages = state.get("messages", [])
    for index in range(len(messages) + 1):
        for title in markers.get(index, []):
            lines.extend([f"## {title}", ""])
        if index == len(messages):
            break
        message = messages[index]
        speaker = "User" if message["role"] == "user" else role
        content = message.get("content", "")
        if message.get("type") == "image":
            match = IMAGE.fullmatch(content)
            content = f"_Abbildung: {match.group(1) or 'Bild'}_" if match else "_Abbildung im Chat_"
        else:
            content = IMAGE.sub(lambda match: f"_Abbildung: {match.group(1) or 'Bild'}_", content)
            if message.get("type") == "bold":
                content = f"**{content}**"
        lines.extend([f"**{speaker}:**", "", content, ""])
    return "\n".join(lines).rstrip() + "\n"


def render_chat_download(activity, state, key="download_chat"):
    filename = re.sub(r"[^a-zA-Z0-9_-]", "_", activity.get("activity_id", "chat"))
    st.download_button(
        "Chat herunterladen",
        data=chat_markdown(activity, state).encode("utf-8"),
        file_name=f"{filename}_chat.md", mime="text/markdown; charset=utf-8",
        key=key, on_click="ignore", disabled=not state.get("messages"),
    )
