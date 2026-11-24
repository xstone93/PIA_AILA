"""Regression coverage for the pilot's conversation and display failures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from activity import enter_task, render_message
from completion import step_complete
import session_store


class PilotFeedbackTest(unittest.TestCase):
    def test_multiline_user_text_is_literal_and_unchanged(self):
        text = "ON | ON\nON | OFF\n\nOFF | ON"
        message = {"role": "user", "content": text}
        with patch("activity.st.caption"), patch("activity.st.text") as render, patch(
            "activity.st.markdown"
        ) as markdown:
            render_message(message)
        render.assert_called_once_with(text)
        markdown.assert_not_called()
        self.assertEqual(message["content"], text)

    def test_completion_reason_reaches_feedback_before_generation(self):
        task = {"task_title": "Dekomposition", "conversation": [{
            "message": "Nenne Ressourcen, Regeln und Ergebnisse."
        }]}
        activity = {"activity_id": "pia_cables_and_tester", "role": "PIA",
                    "activity_name": "Test", "intro_sequence": "intro.md", "tasks": [task]}
        state = {"started": True, "messages": [
            {"role": "user", "content": "EARLIER STEP ANSWER"},
        ], "task_index": 0}
        enter_task(state, task)
        calls = []

        def assess(messages, context, role, assessment=None):
            calls.append("assess")
            self.assertFalse(any("EARLIER STEP ANSWER" in m["content"] for m in messages))
            self.assertEqual(messages[-1]["content"], "2 Kabel, 2 Tester")
            self.assertIn("Nenne Ressourcen, Regeln und Ergebnisse.", context)
            assessment.update(step_complete=False, reason="Regeln und Ergebnisse fehlen.")
            return False

        def feedback(messages, context, **kwargs):
            calls.append("feedback")
            result = json.loads(context.split("APPLICATION ASSESSMENT (private reference data, not instructions)\n")[1])
            self.assertFalse(result["step_complete"])
            self.assertEqual(result["reason"], "Regeln und Ergebnisse fehlen.")
            return "Die Ressourcen stimmen. Welche Regeln und Ergebnisse gibt es?"

        with tempfile.TemporaryDirectory() as temp, patch.object(
            session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
        ), patch("completion.step_complete", side_effect=assess), patch(
            "guardrail.guarded_reply", side_effect=feedback
        ):
            token = session_store.SessionStore().create(activity, state)
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
            app.query_params["session"] = token
            app.run()
            app.chat_input[0].set_value("2 Kabel, 2 Tester").run()
            self.assertFalse(app.exception)
            self.assertEqual(calls, ["assess", "feedback"])
            self.assertFalse(app.session_state["activity_state"]["completion_verified"])
            self.assertNotIn("finish_activity", [b.key for b in app.button])

    def test_assessment_accumulates_current_step_learner_answers(self):
        history = [
            {"role": "assistant", "content": "Nenne A, B und C."},
            {"role": "user", "content": "A"},
            {"role": "assistant", "content": "B und C fehlen."},
            {"role": "user", "content": "B und C"},
        ]
        assessment = {}
        with patch("completion.reply", return_value=json.dumps({
            "reason": "A, B und C beantwortet.", "criteria": [
                {"id": "a", "requirement": "A", "status": "met", "evidence": [1]},
                {"id": "bc", "requirement": "B und C", "status": "met", "evidence": [3]},
            ]
        })) as request:
            self.assertTrue(step_complete(history, "A, B, C", "PIA", assessment))
        self.assertEqual(json.loads(request.call_args.args[0][0]["content"])["conversation"], history)
        self.assertEqual(assessment["reason"], "A, B und C beantwortet.")

    def test_aila_praise_and_continue_do_not_require_coverage_to_finish(self):
        task = {"task_title": "Lernen", "conversation": [{"system_info": "Lernziel: Formel erklären."}]}
        activity = {"activity_id": "aila_robot_and_batteries", "role": "AILA",
                    "activity_name": "Test", "intro_sequence": "robot_and_battery.md", "tasks": [task]}
        state = {"started": True, "messages": [], "task_index": 0}
        enter_task(state, task)
        with tempfile.TemporaryDirectory() as temp, patch.object(
            session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
        ), patch("completion.step_complete") as assess, patch(
            "guardrail.guarded_reply", return_value="Danke!"
        ):
            token = session_store.SessionStore().create(activity, state)
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
            app.query_params["session"] = token
            app.run()
            for text in ("perfekt", "weiter"):
                app.chat_input[0].set_value(text).run()
                self.assertFalse(app.exception)
                self.assertTrue(app.button(key="finish_activity"))
                self.assertFalse(app.session_state["activity_state"]["completed"])
            assess.assert_not_called()


if __name__ == "__main__":
    unittest.main()
