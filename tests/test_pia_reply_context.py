import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from activity import enter_task
from pia_context import reply_context, remember_completed_step
from guardrail import guarded_reply
import session_store


class PiaReplyContextTest(unittest.TestCase):
    def fixture(self):
        activity = {"role": "PIA", "tasks": [
            {"task_title": "Scenario", "conversation": [{"message": "Scenario fact: there are two inputs."}]},
            {"task_title": "Current task", "conversation": [
                {"message": "A supplied definition", "action": "no_wait"},
                {"message": "Explain the result."},
                {"message": "FUTURE SCRIPT"},
            ]},
        ]}
        messages = [
            {"role": "assistant", "content": "Welcome!"},
            {"role": "user", "content": "Hallo, ich bin Daniel. Was gibt es Neues in den Nachrichten?"},
            {"role": "assistant", "content": "Hallo Daniel! Ich bleibe bei unserer Aufgabe."},
            {"role": "assistant", "content": "Explain the result."},
            {"role": "user", "content": "Part one"},
            {"role": "assistant", "content": "What about part two?"},
            {"role": "user", "content": "Part two"},
        ]
        state = {"task_start": 3, "step_start": 3, "task_index": 1, "next_message": 2,
                 "pia_completed_steps": [{"step": [0, 1, 0], "task": "Scenario",
                                           "accepted_requirements": ["Two inputs identified"]}]}
        return activity, state, messages

    def test_current_question_and_safe_background_without_old_refusals(self):
        activity, state, messages = self.fixture()
        original = deepcopy(messages)
        current, background = reply_context(activity, state, messages)
        self.assertEqual(current, messages[3:])
        self.assertEqual(background["quoted_self_introduction"], "ich bin Daniel")
        serialized = json.dumps(background)
        for unwanted in ("Nachrichten", "Ich bleibe", "Hallo Daniel", "FUTURE SCRIPT"):
            self.assertNotIn(unwanted, serialized)
        self.assertIn("two inputs", serialized)
        self.assertIn("A supplied definition", serialized)
        self.assertIn("Two inputs identified", serialized)
        self.assertEqual(messages, original)

    def test_completed_step_memory_stores_requirements_not_raw_dialogue(self):
        _, state, _ = self.fixture()
        assessment = {"criteria": [{"status": "met", "requirement": "Result justified", "evidence": [1]}]}
        for _ in range(2):
            remember_completed_step(state, {"task_title": "Task"}, [1, 2, 3], assessment)
        self.assertEqual(len(state["pia_completed_steps"]), 2)
        self.assertEqual(state["pia_completed_steps"][-1]["accepted_requirements"], ["Result justified"])

    def test_validator_uses_latest_message_and_retries_stale_refusal_or_greeting(self):
        for rejected in ("Hallo Daniel! Die Antwort stimmt.", "Ich bleibe bei unserer Aufgabe. Die Antwort stimmt."):
            with self.subTest(rejected=rejected), patch("guardrail.reply", side_effect=[
                rejected, '{"allowed":false,"violations":["stale greeting/refusal"]}',
                "Die Antwort stimmt.", '{"allowed":true,"violations":[]}',
            ]) as request:
                result = guarded_reply([{"role": "user", "content": "Die beiden Eingaben sind bekannt."}], "Task", "PIA")
                self.assertEqual(result, "Die Antwort stimmt.")
                payload = json.loads(request.call_args_list[1].args[0][0]["content"])
                self.assertEqual(payload["latest_user_message"], "Die beiden Eingaben sind bekannt.")

    def test_app_scopes_only_reply_and_preserves_stored_history(self):
        activity = {"activity_id": "pia_cables_and_tester", "role": "PIA", "activity_name": "Test",
                    "intro_sequence": "intro.md", "tasks": [{"task_title": "Task", "conversation": [
                        {"message": "Explain the result."},
                    ]}]}
        state = {"started": True, "task_index": 0, "messages": [
            {"role": "user", "content": "Hallo, ich bin Daniel. Erzaehl mir Nachrichten."},
            {"role": "assistant", "content": "Ich bleibe bei unserer Aufgabe."},
        ]}
        enter_task(state, activity["tasks"][0])
        with tempfile.TemporaryDirectory() as temp, patch.object(
            session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
        ), patch("completion.step_complete", return_value=True) as assess, patch(
            "guardrail.guarded_reply", return_value="Die Antwort stimmt."
        ) as generation:
            store = session_store.SessionStore()
            token = store.create(activity, state)
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
            app.query_params["session"] = token
            app.run()
            app.chat_input[0].set_value("The result follows.").run()
            self.assertFalse(app.exception)
            self.assertEqual(generation.call_args.args[0], [
                {"role": "assistant", "content": "Explain the result."},
                {"role": "user", "content": "The result follows."},
            ])
            self.assertNotIn("Erzaehl mir Nachrichten", generation.call_args.args[1])
            self.assertEqual(assess.call_args.args[0], generation.call_args.args[0])
            saved = store.load(token)[1]
            self.assertEqual(saved["messages"][:3], state["messages"])
            self.assertTrue(app.button(key="finish_activity"))


if __name__ == "__main__":
    unittest.main()
