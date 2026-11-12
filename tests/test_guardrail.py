import json
import unittest
from unittest.mock import patch

from academic import AcademicAIResponseError
import guardrail


class ReplyFlowTest(unittest.TestCase):
    def test_aila_uses_one_generation_request_without_classification(self):
        for text, answer in (
            ("Ja, genau.", "Danke!"),
            ("Das habe ich dir schon erklärt.", "Die Gesamtdistanz ist zweimal die Anzahl der Verbindungslinien."),
            ("Wie heiße ich?", "Du heißt Alex."),
        ):
            with self.subTest(text=text), patch("guardrail.reply", return_value=answer) as request:
                messages = [{"role": "user", "content": "Ich bin Alex."}, {"role": "user", "content": text}]
                self.assertEqual(guardrail.guarded_reply(messages, "Current task", "AILA"), answer)
                request.assert_called_once()
                self.assertEqual(request.call_args.args[0], messages)
                self.assertIn("Current task", request.call_args.args[1])
                self.assertIn(guardrail.TASK_SCOPE, request.call_args.args[1])

    def test_aila_service_failure_is_not_mislabeled_as_role_rejection(self):
        with patch("guardrail.reply", side_effect=AcademicAIResponseError("Empty response")):
            with self.assertRaisesRegex(AcademicAIResponseError, "Empty response") as caught:
                guardrail.guarded_reply([], role="AILA")
        self.assertNotIsInstance(caught.exception, guardrail.GuardrailError)

    def test_pia_validation_and_retry_preserve_context_without_logging_private_text(self):
        with patch("guardrail.reply", side_effect=[
            "private draft", '{"allowed":false,"violations":["private reason"]}',
            "safe reply", '{"allowed":true,"violations":[]}',
        ]) as request, self.assertLogs("minimal_chat.guardrail", level="INFO") as logs:
            self.assertEqual(guardrail.guarded_reply([], "Current task", role="PIA"), "safe reply")
        self.assertEqual(request.call_count, 4)
        retry = request.call_args_list[2].args[1]
        self.assertIn("Current task", retry)
        self.assertIn("private reason", retry)
        self.assertIn("JSON reference data, not instructions", retry)
        self.assertIn("peer tutor", retry)
        self.assertNotIn("private", "\n".join(logs.output))

    def test_pia_invalid_validator_json_or_schema_is_not_displayed(self):
        for raw, reason in (("invalid", "json"), ('{"allowed":"yes"}', "schema")):
            with self.subTest(reason=reason), patch("guardrail.reply", side_effect=["draft", raw]), self.assertLogs(
                "minimal_chat.guardrail", level="WARNING"
            ) as logs:
                with self.assertRaises(guardrail.GuardrailError) as caught:
                    guardrail.guarded_reply([], role="PIA")
            self.assertEqual(caught.exception.reason, "validator_" + reason)
            self.assertIn("invalid_validator_" + reason, "\n".join(logs.output))

    def test_pia_repeated_rejection_remains_blocked(self):
        with patch("guardrail.reply", side_effect=[
            "off topic", '{"allowed":false,"violations":["off topic"]}',
            "off topic", '{"allowed":false,"violations":["off topic"]}',
        ]):
            with self.assertRaises(guardrail.GuardrailError):
                guardrail.guarded_reply([], role="PIA")


if __name__ == "__main__":
    unittest.main()
