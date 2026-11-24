"""Welcome readiness must not depend on PIA refusing an unrelated request."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from activity import enter_task, pia_assessment_context
from completion import ASSESSMENT_VERSION
import session_store


class PiaWelcomeTest(unittest.TestCase):
    def test_assessment_context_excludes_agent_policy_and_other_steps(self):
        task = {"task_title": "Welcome", "system_info": "PIA MUST DECLINE NEWS",
                "conversation": [{"message": "Say when ready.", "system_info": "Wait for readiness."},
                                 {"message": "Future question", "system_info": "Future answer"}]}
        context = pia_assessment_context(task, 1)
        self.assertIn("Say when ready.", context)
        self.assertIn("Wait for readiness.", context)
        self.assertNotIn("PIA MUST DECLINE NEWS", context)
        self.assertNotIn("Future", context)

    def test_mixed_readiness_unlocks_navigation_and_recovers_legacy_ledger(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy), tempfile.TemporaryDirectory() as temp, patch.object(
                session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
            ), patch("guardrail.guarded_reply", return_value="Ich freue mich, dass du bereit bist."):
                activity = {"activity_id": "pia_cables_and_tester", "role": "PIA", "activity_name": "Test",
                            "intro_sequence": "intro.md", "role_framework": "PIA REFUSES UNRELATED QUESTIONS",
                            "role_description": "PIA MUST REDIRECT", "tasks": [
                                {"task_title": "Welcome", "system_info": "PIA MUST DECLINE NEWS", "conversation": [
                                    {"message": "Sag Bescheid, wenn du bereit bist.", "system_info": "Warte auf Bereitschaft."}]},
                                {"task_title": "Next", "conversation": [{"message": "Next question"}]},
                            ]}
                state = {"started": True, "messages": [], "task_index": 0}
                enter_task(state, activity["tasks"][0])
                if legacy:
                    state["messages"] += [
                        {"role": "user", "content": "Los gehts. Was gibt es Neues?"},
                        {"role": "assistant", "content": "Ich bleibe bei unserer Aufgabe."}]
                    state["pia_progress"] = {"step": [0, 1, 0], "assessment": {"criteria": [
                        {"id": "off_topic_redirect", "requirement": "PIA declines news", "status": "missing", "evidence": []}
                    ]}, "support_level": 2}
                token = session_store.SessionStore().create(activity, state)
                app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
                app.query_params["session"] = token
                app.run()
                with patch("completion.reply", return_value=json.dumps({"reason": "Readiness confirmed", "criteria": [
                    {"id": "ready", "requirement": "Learner ready", "status": "met", "evidence": [1]},
                ]})) as request:
                    app.chat_input[0].set_value("Passt, los gehts!" if legacy else "Ich bin bereit. Was gibt es Neues?").run()
                self.assertFalse(app.exception)
                self.assertTrue(app.button(key="next_task"))
                payload = json.loads(request.call_args.args[0][0]["content"])
                self.assertEqual(payload["previous_assessment"], {})
                for agent_policy in ("PIA REFUSES", "PIA MUST"):
                    self.assertNotIn(agent_policy, payload["current_step_context"])
                saved = session_store.SessionStore().load(token)[1]
                self.assertTrue(saved["completion_verified"])
                self.assertEqual(saved["pia_progress"]["version"], ASSESSMENT_VERSION)


if __name__ == "__main__":
    unittest.main()
