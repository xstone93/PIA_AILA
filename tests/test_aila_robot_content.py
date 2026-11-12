"""Regression checks for the complete tutor-led robot activity."""
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import session_store
from content_registry import activity_base, load_activity, validate_activity
from task_preview import preview_activity
from activity import system_prompt


class AilaRobotContentTest(unittest.TestCase):
    def test_sections_have_one_tutor_led_conversation(self):
        activity = load_activity("aila_robot_and_batteries")
        for task in activity["tasks"][1:]:
            with self.subTest(task=task["task_title"]):
                self.assertEqual(len(task["conversation"]), 1)
                self.assertNotIn("step_name", task["conversation"][0])
                self.assertIn(task["conversation"][0]["system_info"], system_prompt(activity, task, 1))

    def test_legacy_silent_steps_are_available_without_automatic_gates(self):
        from activity import finish_reply
        task = {"task_title": "Muster erkennen", "conversation": [
            {"system_info": "Explain the concept", "step_name": "Old concept phase"},
            {"system_info": "Apply the rule", "step_name": "Old application phase"},
        ]}
        prompt = system_prompt({"role": "AILA"}, task, 1)
        self.assertIn("Explain the concept", prompt)
        self.assertIn("Apply the rule", prompt)
        self.assertNotIn("CURRENT STEP", prompt)
        state = {"next_message": 1}
        finish_reply(state, task, "AILA", True)
        self.assertEqual(state["next_message"], 2)
        self.assertTrue(state["answered"])
        self.assertFalse(state["completion_verified"])

    def test_complete_sequence_and_preparation(self):
        activity = load_activity("aila_robot_and_batteries")
        validate_activity(activity)
        self.assertEqual([t["task_title"] for t in activity["tasks"]], [
            "Willkommen!", "Problemformulierung", "Dekomposition",
            "Verbindungslinien zählen und die Gesamtdistanz berechnen",
            "Muster erkennen", "Verbindungslinien-Formel",
            "Knoten und Verbindungslinien", "Knoten-Formel",
            "Überprüfung beider Formeln",
        ])
        self.assertEqual(activity["tasks"][3]["intro_sequence"], [
            "robot_and_battery_07.md", "robot_and_battery_08.md",
            "robot_and_battery_09.md",
        ])
        for task in activity["tasks"][1:]:
            for filename in task["intro_sequence"]:
                text = (activity_base(activity) / filename).read_text(encoding="utf-8")
                self.assertEqual(text.count("<details>"), text.count("</details>"))
                self.assertEqual(text.count("<summary>"), text.count("</summary>"))
                self.assertNotIn("[AILA Intervention", text)
                self.assertFalse(re.search(r"^AILA:", text, re.MULTILINE))
            self.assertTrue(all("message" not in step for step in task["conversation"]))

    def test_each_section_previews_explanations_in_sidebar(self):
        activity = load_activity("aila_robot_and_batteries")
        with tempfile.TemporaryDirectory() as temp, patch.object(
            session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
        ):
            store = session_store.SessionStore(Path(temp) / "preview_sessions.sqlite3")
            for index, task in enumerate(activity["tasks"][1:], 1):
                with self.subTest(section=task["task_title"]):
                    content, state = preview_activity(activity, index)
                    token = store.create(content, state)
                    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
                    app.query_params["preview"] = "1"
                    app.query_params["session"] = token
                    app.run()
                    self.assertFalse(app.exception)
                    self.assertEqual(app.sidebar.subheader[0].value, task["task_title"])
                    self.assertEqual(len(app.chat_message), 0)
                    for _ in task["intro_sequence"][1:]:
                        app.button(key="intro_next").click().run()
                        self.assertFalse(app.exception)
                    app.button(key="confirm_intro").click().run()
                    self.assertFalse(app.exception)
                    self.assertEqual([h.value for h in app.main.subheader], [task["task_title"]])
                    self.assertEqual(len(app.chat_input), 1)
                    self.assertEqual(len(app.chat_message), 0)

    def test_tutor_can_keep_talking_then_explicitly_finish_without_classification(self):
        activity = load_activity("aila_robot_and_batteries")
        with tempfile.TemporaryDirectory() as temp, patch.object(
            session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
        ):
            content, state = preview_activity(activity, 1)
            store = session_store.SessionStore(Path(temp) / "preview_sessions.sqlite3")
            token = store.create(content, state)
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
            app.query_params["preview"] = "1"
            app.query_params["session"] = token
            app.run()
            app.button(key="confirm_intro").click().run()
            exchanges = [
                ("Ein Muster ist etwas Regelmäßiges, das immer wieder kommt.", "Ich verstehe, danke!"),
                ("Ja genau, das stimmt so.", "Danke!"),
                ("Das habe ich dir schon erklärt. Was ist das Ziel?", "Eine allgemeine Regel für die Distanz."),
            ]
            for tutor, response in exchanges:
                with patch("guardrail.reply", return_value=response) as generation, patch(
                    "completion.step_complete"
                ) as completion:
                    app.chat_input[0].set_value(tutor).run()
                app.run()
                self.assertFalse(app.exception)
                generation.assert_called_once()
                completion.assert_not_called()
                self.assertEqual([h.value for h in app.main.subheader], ["Problemformulierung"])
                self.assertTrue(app.button(key="finish_activity"))
                self.assertFalse(app.session_state["activity_state"]["completed"])
                self.assertFalse(app.session_state["activity_state"]["completion_verified"])
            app.button(key="finish_activity").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.session_state["activity_state"]["completed"])


if __name__ == "__main__":
    unittest.main()
