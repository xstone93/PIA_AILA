import json
import unittest
from unittest.mock import patch

import guardrail
from academic import AcademicAIResponseError


class TaskScopeTest(unittest.TestCase):
    def test_diagnostics_distinguish_rejection_and_retry_without_private_text(self):
        with patch("guardrail.reply", side_effect=[
            "private draft", '{"allowed":false,"violations":["private reason"]}',
            "safe reply", '{"allowed":true,"violations":[]}',
        ]), self.assertLogs("minimal_chat.guardrail", level="INFO") as logs:
            self.assertEqual(guardrail.guarded_reply([], role="PIA"), "safe reply")
        output = "\n".join(logs.output)
        self.assertIn("guardrail_rejected role=PIA attempt=1 violation_count=1", output)
        self.assertIn("guardrail_accepted role=PIA attempt=2", output)
        self.assertNotIn("private", output)

    def test_diagnostics_distinguish_invalid_json_and_schema(self):
        for raw, reason in (("private invalid JSON", "json"),
                            ('{"allowed":"private"}', "schema")):
            with self.subTest(reason=reason), patch("guardrail.reply", side_effect=["draft", raw]), self.assertLogs(
                "minimal_chat.guardrail", level="WARNING"
            ) as logs:
                with self.assertRaises(AcademicAIResponseError):
                    guardrail.guarded_reply([], role="AILA")
            output = "\n".join(logs.output)
            self.assertIn(f"invalid_validator_{reason} role=AILA attempt=1", output)
            self.assertIn("guardrail_failed role=AILA attempts=1", output)
            self.assertNotIn("private", output)

    def test_invalid_api_response_identifies_phase_without_exception_text(self):
        for phase, responses in (
            ("generation", [AcademicAIResponseError("private body")]),
            ("validation", ["draft", AcademicAIResponseError("private body")]),
        ):
            with self.subTest(phase=phase), patch("guardrail.reply", side_effect=responses), self.assertLogs(
                "minimal_chat.guardrail", level="WARNING"
            ) as logs:
                with self.assertRaises(AcademicAIResponseError):
                    guardrail.guarded_reply([], role="PIA")
            self.assertIn(f"invalid_api_response role=PIA phase={phase} attempt=1", logs.output[0])
            self.assertNotIn("private", "\n".join(logs.output))

    def test_unrelated_draft_is_replaced_and_task_context_reaches_validator(self):
        messages = [{"role": "user", "content": "Was ist die Quadratwurzel von 10?"}]
        refusal = "Ich bleibe bei den Fragen zu unseren Aufgaben."
        for role in ("PIA", "AILA"):
            with self.subTest(role=role), patch("guardrail.reply", side_effect=[
                "Unrelated answer followed by a redirect",
                '{"allowed":false,"violations":["off topic"]}',
                refusal,
                '{"allowed":true,"violations":[]}',
            ]) as reply:
                result = guardrail.guarded_reply(messages, "CURRENT TASK: Kabel und Tester", role)
                self.assertEqual(result, refusal)
                for call in (reply.call_args_list[0], reply.call_args_list[2]):
                    self.assertIn(guardrail.TASK_SCOPE, call.args[1])
                payload = json.loads(reply.call_args_list[1].args[0][0]["content"])
                self.assertEqual(payload["task_context"], "CURRENT TASK: Kabel und Tester")
                self.assertEqual(payload["conversation"], messages)

    def test_repeated_scope_violation_is_never_displayed(self):
        for role in ("PIA", "AILA"):
            with self.subTest(role=role), patch("guardrail.reply", side_effect=[
                "Off-topic answer", '{"allowed":false,"violations":["off topic"]}',
                "Delayed off-topic answer", '{"allowed":false,"violations":["off topic"]}',
            ]):
                with self.assertRaises(AcademicAIResponseError):
                    guardrail.guarded_reply([], "CURRENT TASK: Kabel und Tester", role)


if __name__ == "__main__":
    unittest.main()
