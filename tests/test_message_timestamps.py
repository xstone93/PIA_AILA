from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from activity import enter_task, start_conversation
from chat_export import chat_markdown
from content_registry import load_activity
from task_preview import preview_activity
from timing import show_message_timestamp
import session_store


class MessageTimestampTest(unittest.TestCase):
    def test_scripted_messages_are_stamped_only_when_revealed(self):
        task = {"conversation": [
            {"message": "Willkommen", "action": "no_wait"}, {"message": "Erste Frage"},
        ]}
        state = {"messages": []}
        with patch("activity.utc_timestamp", side_effect=[
            "2026-11-12T09:00:00+00:00", "2026-11-12T09:00:01+00:00",
        ]) as clock:
            enter_task(state, task)
            original = deepcopy(state["messages"])
            start_conversation(state, task)
        self.assertEqual(clock.call_count, 1)
        self.assertEqual(state["messages"], original)
        self.assertEqual(original[0]["timestamp"], "2026-11-12T09:00:00+00:00")
        self.assertEqual(original[1]["timestamp"], "2026-11-12T09:00:00+00:00")
        self.assertEqual(original[0]["script_batch"], original[1]["script_batch"])

    def test_only_same_script_batch_shares_a_timestamp_header(self):
        first = {"role": "assistant", "timestamp": "same", "script_batch": 0}
        self.assertFalse(show_message_timestamp(dict(first), first))
        self.assertTrue(show_message_timestamp({**first, "script_batch": 3}, first))
        self.assertTrue(show_message_timestamp({"role": "assistant", "timestamp": "same"}, first))
        self.assertTrue(show_message_timestamp({**first, "role": "user"}, first))
        self.assertTrue(show_message_timestamp(first))

    def test_no_wait_batch_has_one_header_in_chat_export_and_after_resume(self):
        activity = {"activity_id": "pia_cables_and_tester", "role": "PIA", "activity_name": "Test",
                    "intro_sequence": "intro.md", "tasks": [{"task_title": "Task", "conversation": [
                        {"message": "First block", "action": "no_wait"},
                        {"message": "Second block", "type": "bold", "action": "no_wait"},
                        {"message": "Current question"},
                        {"message": "Later question"},
                    ]}]}
        stamp = "2026-11-12T09:00:00+00:00"
        with tempfile.TemporaryDirectory() as temp, patch.object(
            session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
        ), patch("activity.utc_timestamp", return_value=stamp), patch("timing.utc_timestamp", return_value=stamp), patch(
            "completion.step_complete", return_value=True
        ), patch("guardrail.guarded_reply", return_value="Feedback"):
            state = {"started": True, "task_index": 0, "messages": []}
            enter_task(state, activity["tasks"][0])
            store = session_store.SessionStore()
            token = store.create(activity, state)
            app_path = str(Path(__file__).resolve().parents[1] / "app.py")
            app = AppTest.from_file(app_path)
            app.query_params["session"] = token
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(sum(len(m.caption) for m in app.chat_message), 1)
            export = chat_markdown(activity, store.load(token)[1])
            self.assertEqual(export.count("**PIA:**"), 1)
            for block in ("First block", "Second block", "Current question"):
                self.assertIn(block, export)
            self.assertNotIn("Later question", export)
            app.chat_input[0].set_value("Answer").run()
            app.run()
            self.assertFalse(app.exception)
            # One batch + user + generated answer + new scripted question.
            self.assertEqual(sum(len(m.caption) for m in app.chat_message), 4)
            saved = store.load(token)[1]
            export = chat_markdown(activity, saved)
            self.assertEqual(export.count("**PIA:**"), 3)
            self.assertEqual(export.count("**User:**"), 1)
            resumed = AppTest.from_file(app_path)
            resumed.query_params["session"] = token
            resumed.run()
            self.assertFalse(resumed.exception)
            self.assertEqual(sum(len(m.caption) for m in resumed.chat_message), 4)
            self.assertEqual(store.load(token)[1], saved)

    def test_user_and_agent_times_persist_and_match_chat_and_export(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
            session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
        ):
            activity, state = preview_activity(load_activity("aila_robot_and_batteries"), 1)
            store = session_store.SessionStore(Path(temp) / "preview_sessions.sqlite3")
            token = store.create(activity, state)
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
            app.query_params["preview"] = "1"
            app.query_params["session"] = token
            app.run()
            for _ in activity["tasks"][0].get("intro_sequence", [])[1:]:
                app.button(key="intro_next").click().run()
            app.button(key="confirm_intro").click().run()
            times = ["2026-11-12T09:00:00+00:00", "2026-11-12T09:00:04+00:00"]
            with patch("timing.utc_timestamp", side_effect=times), patch(
                "guardrail.reply", return_value="Danke!"
            ) as generation:
                app.chat_input[0].set_value("Ein Muster wiederholt sich.").run()
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(generation.call_args.args[0], [
                {"role": "user", "content": "Ein Muster wiederholt sich."},
            ])
            saved = store.load(token)[1]
            self.assertEqual([m["timestamp"] for m in saved["messages"]], times)
            self.assertEqual(app.chat_message[0].caption[0].value, "12.11.2026 10:00:00 CET")
            self.assertEqual(app.chat_message[1].caption[0].value, "12.11.2026 10:00:04 CET")
            export = chat_markdown(activity, saved)
            self.assertIn("**User:** _12.11.2026 10:00:00 CET_", export)
            self.assertIn("**AILA:** _12.11.2026 10:00:04 CET_", export)
            app.run()
            self.assertEqual(store.load(token)[1]["messages"], saved["messages"])
            resumed = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
            resumed.query_params["preview"] = "1"
            resumed.query_params["session"] = token
            resumed.run()
            self.assertFalse(resumed.exception)
            self.assertEqual(resumed.chat_message[0].caption[0].value, "12.11.2026 10:00:00 CET")


if __name__ == "__main__":
    unittest.main()
