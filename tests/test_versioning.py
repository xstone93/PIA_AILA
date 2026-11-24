from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from activity import enter_task
from app_version import APP_VERSION
from chat_export import chat_markdown
from session_store import SessionStore
import session_store


class VersioningTest(unittest.TestCase):
    def test_new_session_and_study_snapshots_record_version_without_mutating_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SessionStore(Path(temp) / "sessions.sqlite3")
            for activity in ({"role": "PIA"}, {"kind": "study", "activities": {"example": {"role": "AILA"}}}):
                with self.subTest(study=activity.get("kind")):
                    original = deepcopy(activity)
                    with patch("session_store.APP_VERSION", "0.1.0"):
                        token = store.create(activity, {"messages": []})
                    with patch("session_store.APP_VERSION", "0.2.0"):
                        restored, state, revision = store.load(token)
                        store.save(token, {**state, "started": True}, revision)
                    self.assertEqual(store.load(token)[0]["app_version"], "0.1.0")
                    if activity.get("kind") == "study":
                        self.assertEqual(restored["activities"]["example"]["app_version"], "0.1.0")
                    self.assertEqual(activity, original)

    def test_export_distinguishes_start_export_and_message_versions(self):
        state = {"messages": [
            {"role": "user", "content": "Before update", "app_version": "0.1.0"},
            {"role": "assistant", "content": "After update", "app_version": "0.2.0"},
        ]}
        with patch("chat_export.APP_VERSION", "0.3.0"):
            export = chat_markdown({"role": "PIA", "app_version": "0.1.0"}, state)
        self.assertIn("Softwareversion beim Sitzungsstart: 0.1.0", export)
        self.assertIn("Exportiert mit Softwareversion: 0.3.0", export)
        self.assertIn("Version: 0.1.0", export)
        self.assertIn("Version: 0.2.0", export)

    def test_legacy_records_are_not_relabelled_as_current(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SessionStore(Path(temp) / "sessions.sqlite3")
            with store.connect() as connection:
                connection.execute("INSERT INTO sessions (id, activity, state) VALUES (?, ?, ?)",
                                   ("a" * 43, json.dumps({"role": "PIA"}), json.dumps({"messages": [
                                       {"role": "user", "content": "Historic"},
                                   ]})))
            activity, state, _ = store.load("a" * 43)
            self.assertNotIn("app_version", activity)
            self.assertNotIn("app_version", state["messages"][0])
            export = chat_markdown(activity, state)
            self.assertIn("Softwareversion beim Sitzungsstart: Nicht erfasst", export)
            self.assertIn("Version: Nicht erfasst", export)
            self.assertIn(f"Exportiert mit Softwareversion: {APP_VERSION}", export)

    def test_app_displays_current_version_and_stamps_only_new_messages(self):
        activity = {"activity_id": "pia_cables_and_tester", "role": "PIA", "activity_name": "Test",
                    "intro_sequence": "intro.md", "tasks": [{"task_title": "Welcome", "conversation": [
                        {"message": "Bist du bereit?"},
                    ]}]}
        state = {"started": True, "task_index": 0, "messages": []}
        enter_task(state, activity["tasks"][0])
        original = deepcopy(state["messages"])
        self.assertEqual(original[0]["app_version"], APP_VERSION)
        with tempfile.TemporaryDirectory() as temp, patch.object(
            session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
        ), patch("completion.step_complete", return_value=True), patch(
            "guardrail.guarded_reply", return_value="Danke!"
        ), patch("app_version.APP_VERSION", "0.2.0"):
            store = SessionStore()
            token = store.create(activity, state)
            app_path = str(Path(__file__).resolve().parents[1] / "app.py")
            app = AppTest.from_file(app_path)
            app.query_params["session"] = token
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any("Softwareversion 0.2.0" in caption.value for caption in app.caption))
            app.chat_input[0].set_value("Ich bin bereit.").run()
            app.run()
            self.assertFalse(app.exception)
            snapshot, saved, _ = store.load(token)
            self.assertEqual(snapshot["app_version"], APP_VERSION)
            self.assertEqual(saved["messages"][:1], original)
            self.assertEqual([message["app_version"] for message in saved["messages"][1:]], ["0.2.0", "0.2.0"])


if __name__ == "__main__":
    unittest.main()
