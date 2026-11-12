from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
import requests

from academic import AcademicAIResponseError
from activity import enter_task, system_prompt
from completion import step_complete
import session_store


class StepCompletionTest(unittest.TestCase):
    def test_completion_service_failure_is_explained_and_does_not_unlock_navigation(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
            session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
        ), patch("guardrail.guarded_reply", return_value="Danke!"), patch(
            "completion.reply", return_value="not JSON"
        ):
            activity = {"activity_id": "pia_cables_and_tester", "role": "PIA",
                        "activity_name": "Test", "intro_sequence": "intro.md",
                        "sidebar_reference": "intro.md", "tasks": [
                            {"task_title": "Fragen", "conversation": [{"system_info": "Wait"}]}]}
            state = {"started": True, "completed": False, "task_index": 0, "messages": []}
            enter_task(state, activity["tasks"][0])
            token = session_store.SessionStore().create(activity, state)
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
            app.query_params["session"] = token
            app.run()
            app.chat_input[0].set_value("Ja, genau.").run()
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.session_state["activity_state"]["messages"]), 2)
            self.assertFalse(app.session_state["activity_state"]["completion_verified"])
            self.assertNotIn("finish_activity", [button.key for button in app.button])
            self.assertIn("Abschlussprüfung ist technisch fehlgeschlagen", app.warning[0].value)
            self.assertIn("Fehlerreferenz:", app.warning[0].value)
            with patch("completion.step_complete", return_value=True):
                app.chat_input[0].set_value("Ja, richtig verstanden.").run()
            app.run()
            self.assertFalse(app.exception)
            self.assertFalse(app.warning)
            self.assertTrue(app.button(key="finish_activity"))

    def test_navigation_alone_never_completes_pia(self):
        for role in ("PIA",):
            with self.subTest(role=role), patch("completion.reply") as request:
                self.assertFalse(step_complete([{"role": "user", "content": "weiter"}], "Weiter!", "Task", role))
                request.assert_not_called()

    def test_invalid_decisions_and_service_errors_keep_step_open(self):
        for result in ("invalid", '{}', '{"step_complete":"true"}',
                       AcademicAIResponseError("private"), requests.Timeout()):
            with self.subTest(result=type(result).__name__), patch("completion.reply") as request:
                if isinstance(result, Exception):
                    request.side_effect = result
                else:
                    request.return_value = result
                self.assertFalse(step_complete([{"role": "user", "content": "Antwort"}], "Feedback", "Task", "PIA"))

    def test_role_and_current_step_history_reach_completion_check(self):
        for role in ("PIA",):
            for complete in (True, False):
                with self.subTest(role=role, complete=complete), patch(
                    "completion.reply", return_value=json.dumps({"step_complete": complete})
                ) as request:
                    history = [{"role": "user", "content": "Meine Überlegung"}]
                    self.assertIs(step_complete(history, "Feedback", "Current criteria", role), complete)
                    payload = json.loads(request.call_args.args[0][0]["content"])
                    self.assertEqual(payload["role"], role)
                    self.assertEqual(payload["conversation"], history)
                    self.assertEqual(payload["current_step_context"], "Current criteria")

    def test_prior_step_answer_key_is_not_reused(self):
        task = {"task_title": "Muster", "conversation": [
            {"message": "Question 1", "system_info": "OLD ANSWER"},
            {"message": "Question 2", "system_info": "CURRENT ANSWER"},
            {"message": "Question 3", "system_info": "FUTURE ANSWER"},
        ]}
        prompt = system_prompt({"role": "PIA"}, task, 2)
        self.assertIn("CURRENT ANSWER", prompt)
        self.assertNotIn("OLD ANSWER", prompt)
        self.assertNotIn("FUTURE ANSWER", prompt)

    def test_ui_requires_completion_before_advancement_and_navigation(self):
        for role in ("PIA",):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as temp, patch.object(
                session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
            ), patch("guardrail.guarded_reply", return_value="Bitte ergänze deine Antwort."):
                activity = {"activity_id": role.lower() + "_cables_and_tester",
                            "role": role, "activity_name": "Test", "intro_sequence": "intro.md",
                            "sidebar_reference": "intro.md",
                            "tasks": [{"task_title": "Fragen", "conversation": [
                                {"message": "Erste Frage?"}, {"message": "Zweite Frage?"}]},
                                {"task_title": "Nächstes Thema", "conversation": [{"message": "Später"}]}]}
                state = {"started": True, "completed": False, "task_index": 0, "messages": []}
                enter_task(state, activity["tasks"][0])
                token = session_store.SessionStore().create(activity, state)
                app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
                app.query_params["session"] = token
                app.run()
                # Navigation, wrong/partial answers, clarification and failed checks stay put.
                for text in ("weiter", "falsch", "teilweise", "was?"):
                    with patch("completion.step_complete", return_value=False):
                        app.chat_input[0].set_value(text).run()
                    app.run()
                    self.assertFalse(app.exception)
                    self.assertEqual(app.session_state["activity_state"]["next_message"], 1)
                    self.assertFalse(app.session_state["activity_state"]["answered"])
                    self.assertNotIn("next_task", [b.key for b in app.button])
                with patch("completion.step_complete", return_value=True):
                    app.chat_input[0].set_value("Vollständige Antwort").run()
                app.run()
                self.assertEqual(app.session_state["activity_state"]["next_message"], 2)
                self.assertNotIn("next_task", [b.key for b in app.button])
                with patch("completion.step_complete", return_value=False):
                    app.chat_input[0].set_value("Noch unvollständig").run()
                app.run()
                self.assertNotIn("next_task", [b.key for b in app.button])
                # An accepted final learner answer unlocks PIA navigation.
                with patch("completion.step_complete", return_value=True):
                    app.chat_input[0].set_value("Jetzt vollständig bestätigt").run()
                app.run()
                self.assertTrue(app.button(key="next_task"))
                resumed = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
                resumed.query_params["session"] = token
                resumed.run()
                self.assertTrue(resumed.button(key="next_task"))


if __name__ == "__main__":
    unittest.main()
