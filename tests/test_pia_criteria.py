import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from activity import enter_task
from completion import validate_assessment, step_complete
import session_store


def criterion(key, status, evidence):
    return {"id": key, "requirement": key, "status": status, "evidence": evidence}


class PiaCriteriaTest(unittest.TestCase):
    def setUp(self):
        self.history = [
            {"role": "assistant", "content": "Explain the conditions and justify the result."},
            {"role": "user", "content": "The condition holds."},
            {"role": "assistant", "content": "Why?"},
            {"role": "user", "content": "Because of the invariant."},
        ]
        self.previous = {"criteria": [criterion("condition", "met", [1]),
                                      criterion("reason", "missing", [])]}

    def test_omitting_an_accepted_part_does_not_erase_it(self):
        result = validate_assessment({"reason": "Only reasoning supplied.", "criteria": [
            criterion("condition", "missing", []), criterion("reason", "met", [3]),
        ]}, self.history, self.previous)
        self.assertTrue(result["step_complete"])
        self.assertEqual(result["criteria"][0]["evidence"], [1])

    def test_later_contradiction_reopens_only_affected_criterion(self):
        history = self.history + [{"role": "user", "content": "Actually the condition is false."}]
        result = validate_assessment({"reason": "Later contradiction.", "criteria": [
            criterion("condition", "incorrect", [4]), criterion("reason", "met", [3]),
        ]}, history, self.previous)
        self.assertFalse(result["step_complete"])
        self.assertEqual(result["criteria"][0]["status"], "incorrect")

    def test_old_error_cannot_erase_later_accepted_answer(self):
        previous = {"criteria": [criterion("answer", "met", [3])]}
        result = validate_assessment({"reason": "Older error.", "criteria": [
            criterion("answer", "incorrect", [1]),
        ]}, self.history, previous)
        self.assertTrue(result["step_complete"])

    def test_invalid_evidence_and_changing_requirements_fail_closed(self):
        cases = [
            [criterion("condition", "met", [0]), criterion("reason", "missing", [])],
            [criterion("condition", "met", [99]), criterion("reason", "missing", [])],
            [criterion("condition", "met", [True]), criterion("reason", "missing", [])],
            [criterion("condition", "met", []), criterion("reason", "missing", [])],
            [criterion("new_requirement", "missing", [])],
            [criterion("condition", "met", [1]), criterion("condition", "missing", [])],
        ]
        for criteria in cases:
            with self.subTest(criteria=criteria), self.assertRaises(ValueError):
                validate_assessment({"reason": "Test", "criteria": criteria}, self.history, self.previous)

    def test_python_derives_completion_instead_of_trusting_model_boolean(self):
        result = validate_assessment({"step_complete": True, "reason": "Test", "criteria": [
            criterion("reason", "missing", []),
        ]}, self.history, {})
        self.assertFalse(result["step_complete"])

    def test_prior_assessment_is_passed_as_reference(self):
        assessment = {"previous": deepcopy(self.previous)}
        decision = {"reason": "Complete", "criteria": [
            criterion("condition", "met", [1]), criterion("reason", "met", [3]),
        ]}
        with patch("completion.reply", return_value=json.dumps(decision)) as request:
            self.assertTrue(step_complete(self.history, "Generic task", "PIA", assessment))
        payload = json.loads(request.call_args.args[0][0]["content"])
        self.assertEqual(payload["previous_assessment"], self.previous)
        self.assertEqual(payload["learner_evidence"], [
            {"message_index": 1, "content": self.history[1]["content"]},
            {"message_index": 3, "content": self.history[3]["content"]},
        ])

    def test_navigation_preserves_accepted_parts_without_model_call(self):
        assessment = {"previous": deepcopy(self.previous)}
        with patch("completion.reply") as request:
            self.assertFalse(step_complete(self.history + [{"role": "user", "content": "weiter"}],
                                           "Task", "PIA", assessment))
        request.assert_not_called()
        self.assertEqual(assessment["criteria"], self.previous["criteria"])

    def test_progress_survives_resume_and_resets_for_next_question(self):
        activity = {"activity_id": "pia_cables_and_tester", "role": "PIA",
                    "activity_name": "Generic", "intro_sequence": "intro.md", "tasks": [{
                        "task_title": "Task", "conversation": [
                            {"message": "Explain a condition and justify it."},
                            {"message": "A different question."},
                        ],
                    }]}
        state = {"started": True, "messages": [], "task_index": 0}
        enter_task(state, activity["tasks"][0])
        decisions = [
            {"reason": "Reason missing", "criteria": [criterion("condition", "met", [1]),
                                                        criterion("reason", "missing", [])]},
            {"reason": "Complete", "criteria": [criterion("condition", "met", [1]),
                                                  criterion("reason", "met", [3])]},
        ]
        with tempfile.TemporaryDirectory() as temp, patch.object(
            session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
        ), patch("guardrail.guarded_reply", return_value="Explain why."), patch(
            "completion.reply", side_effect=[json.dumps(d) for d in decisions]
        ) as request:
            store = session_store.SessionStore()
            token = store.create(activity, state)
            app_path = str(Path(__file__).resolve().parents[1] / "app.py")
            app = AppTest.from_file(app_path)
            app.query_params["session"] = token
            app.run()
            app.chat_input[0].set_value("The condition holds.").run()
            self.assertFalse(app.exception)
            saved = store.load(token)[1]
            self.assertEqual(saved["pia_progress"]["support_level"], 2)
            resumed = AppTest.from_file(app_path)
            resumed.query_params["session"] = token
            resumed.run()
            resumed.chat_input[0].set_value("Because of the invariant.").run()
            self.assertFalse(resumed.exception)
            payload = json.loads(request.call_args.args[0][0]["content"])
            self.assertEqual(payload["previous_assessment"]["criteria"], decisions[0]["criteria"])
            self.assertEqual(store.load(token)[1]["next_message"], 2)
            self.assertNotIn("pia_progress", store.load(token)[1])


if __name__ == "__main__":
    unittest.main()
