from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import session_store
from content_registry import load_activity
from task_preview import preview_activity


APP = str(Path(__file__).resolve().parents[1] / "app.py")


class PreviewTest(unittest.TestCase):
    def setUp(self):
        completion = patch("completion.step_complete", return_value=True)
        completion.start()
        self.addCleanup(completion.stop)

    def test_pattern_questions_share_one_heading_and_finish_after_last_entry(self):
        activity = load_activity("pia_cables_and_tester")
        titles = [task["task_title"] for task in activity["tasks"]]
        self.assertEqual(len(titles), len(set(titles)))
        index = titles.index("Muster erkennen")
        self.assertEqual(len(activity["tasks"][index]["conversation"]), 4)
        with tempfile.TemporaryDirectory() as temp, patch.object(
            session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
        ):
            content, state = preview_activity(activity, index)
            token = session_store.SessionStore(Path(temp) / "preview_sessions.sqlite3").create(content, state)
            app = AppTest.from_file(APP)
            app.query_params["preview"] = "1"
            app.query_params["session"] = token
            app.run()
            for revealed in (1, 2, 3):
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["activity_state"]["next_message"], revealed)
                self.assertEqual([h.value for h in app.main.subheader], ["Muster erkennen"])
                self.assertNotIn("finish_activity", [b.key for b in app.button])
                with patch("guardrail.guarded_reply", return_value="Danke für deine Überlegung."):
                    app.chat_input[0].set_value(f"Meine Antwort {revealed}").run()
                app.run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state["activity_state"]["next_message"], 4)
            self.assertEqual([h.value for h in app.main.subheader], ["Muster erkennen"])
            self.assertTrue(app.button(key="finish_activity"))
            self.assertEqual(app.get("progress")[0].proto.value, 0)
            app.button(key="finish_activity").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.get("progress")[0].proto.value, 100)
            self.assertEqual(app.get("progress")[0].proto.text, "Abgeschlossen")

    def test_pia_context_is_in_chat_and_only_glossary_in_sidebar(self):
        activity = load_activity("pia_cables_and_tester")
        self.assertTrue(all(not task.get("intro_sequence") for task in activity["tasks"]))
        scenario = "\n".join(entry.get("message", "") for entry in activity["tasks"][1]["conversation"])
        self.assertIn("Genau eines der beiden Kabel ist defekt", scenario)
        with tempfile.TemporaryDirectory() as temp, patch.object(
            session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
        ):
            content, state = preview_activity(activity, 1)
            token = session_store.SessionStore(Path(temp) / "preview_sessions.sqlite3").create(content, state)
            app = AppTest.from_file(APP)
            app.query_params["preview"] = "1"
            app.query_params["session"] = token
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(app.chat_input)
            sidebar = "\n".join(m.value for m in app.sidebar.markdown)
            main = "\n".join(m.value for m in app.main.markdown)
            self.assertIn("Wichtige Begriffe", sidebar)
            self.assertIn("Ergebniskombination", sidebar)
            self.assertNotIn("Genau eines der beiden Kabel ist defekt", sidebar)
            self.assertIn("Genau eines der beiden Kabel ist defekt", main)
            if "![" in scenario:
                self.assertTrue(app.main.get("imgs"))
            self.assertFalse(app.sidebar.get("imgs"))
            self.assertTrue(app.button(key="open_intro"))
            app.button(key="open_intro").click().run()
            self.assertTrue(app.chat_input)
            self.assertFalse(app.exception)

    def test_single_task_isolated_without_mutating_original(self):
        original = load_activity("pia_cables_and_tester")
        activity, state = preview_activity(original, 7)
        self.assertEqual(len(activity["tasks"]), 1)
        self.assertEqual(activity["tasks"][0], original["tasks"][7])
        self.assertGreater(len(original["tasks"]), 1)
        self.assertTrue(state["started"])
        self.assertEqual(len(state["messages"]), 1)
        self.assertNotIn("phase", state)
        whole, state = preview_activity(original)
        self.assertEqual(whole["tasks"], original["tasks"])
        self.assertFalse(state["started"])

    def test_preview_picker_chat_resume_and_reset(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
            session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
        ):
            app = AppTest.from_file(APP)
            app.query_params["preview"] = "1"
            app.run()
            self.assertFalse(app.exception)
            app.selectbox(key="preview_activity").select("pia_cables_and_tester").run()
            app.selectbox(key="preview_task_pia_cables_and_tester").select(7).run()
            app.button(key="preview_start").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.chat_input)
            token = app.query_params["session"]
            self.assertEqual(len(app.get("download_button")), 1)
            if isinstance(token, list):
                token = token[0]
            store = session_store.SessionStore(Path(temp) / "preview_sessions.sqlite3")
            content, state, _ = store.load(token)
            self.assertEqual(len(content["tasks"]), 1)
            self.assertNotIn("group", state)
            self.assertFalse((Path(temp) / "sessions.sqlite3").exists())
            with patch("guardrail.guarded_reply", return_value="Danke."):
                app.chat_input[0].set_value("Meine Antwort").run()
            self.assertFalse(app.exception)
            self.assertTrue(app.button(key="finish_activity"))
            resumed = AppTest.from_file(APP)
            resumed.query_params["preview"] = "1"
            resumed.query_params["session"] = token
            resumed.run()
            self.assertFalse(resumed.exception)
            self.assertTrue(any(m.value == "Meine Antwort" for m in resumed.markdown))
            resumed.button(key="preview_reset").click().run()
            self.assertFalse(resumed.exception)
            self.assertTrue(resumed.button(key="preview_start"))
            self.assertNotIn("session", resumed.query_params)
            self.assertEqual(store.load(token)[1]["messages"][-1]["content"], "Danke.")


if __name__ == "__main__":
    unittest.main()
