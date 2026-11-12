import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import requests

import diagnostics
from completion import step_complete
from guardrail import GuardrailError, guarded_reply


class DiagnosticsTest(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, "open") as output:
            diagnostics.record("test", "reference", draft="private")
        output.assert_not_called()

    def test_rejection_retry_and_completion_share_reference_without_normal_log_content(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"AILA_DIAGNOSTICS": "1"}), patch.object(
            diagnostics, "DIAGNOSTICS_PATH", Path(temp) / "diagnostics.jsonl"
        ), diagnostics.diagnostic_scope(task_title="Muster", step=1) as context:
            with patch("guardrail.reply", side_effect=[
                "private draft", '{"allowed":false,"violations":["private reason"]}',
                "Danke!", '{"allowed":true,"violations":[]}',
            ]), self.assertLogs("minimal_chat.guardrail", level="INFO") as logs:
                self.assertEqual(guarded_reply([], "private task context", role="PIA"), "Danke!")
            with patch("completion.reply", return_value="invalid"):
                self.assertFalse(step_complete([], "Danke!", "private task context", "PIA"))
            entries = [json.loads(line) for line in diagnostics.DIAGNOSTICS_PATH.read_text(encoding="utf-8").splitlines()]
            self.assertEqual({entry["reference"] for entry in entries}, {context["reference"]})
            self.assertEqual([entry["event"] for entry in entries], [
                "guardrail_rejected", "guardrail_accepted", "completion_check_failed",
            ])
            self.assertEqual(entries[0]["draft"], "private draft")
            self.assertEqual(entries[0]["violations"], ["private reason"])
            self.assertEqual(entries[0]["current_step_context"], "private task context")
            self.assertEqual(context["completion_error"], context["reference"])
            self.assertNotIn("private", "\n".join(logs.output))

    def test_failure_kinds_have_distinct_messages_and_references(self):
        for responses, reason in (
            (["draft", "invalid"], "validator_json"),
            (["draft", '{"allowed":"yes"}'], "validator_schema"),
            (["draft", '{"allowed":false,"violations":["reason"]}'] * 2, "rejected"),
        ):
            with self.subTest(reason=reason), patch("guardrail.reply", side_effect=responses), diagnostics.diagnostic_scope() as context:
                with self.assertRaises(GuardrailError) as caught:
                    guarded_reply([], role="PIA")
                self.assertEqual(caught.exception.reason, reason)
                self.assertIn(context["reference"], str(caught.exception))
                self.assertIn("nicht als falsch bewertet", str(caught.exception))
                self.assertIn("nicht gespeichert", str(caught.exception))

    def test_validator_service_failure_is_distinct_from_rejection(self):
        with patch("guardrail.reply", side_effect=["draft", requests.Timeout()]), diagnostics.diagnostic_scope() as context:
            with self.assertRaises(GuardrailError) as caught:
                guarded_reply([], role="PIA")
            self.assertEqual(caught.exception.reason, "validation_service")
            self.assertIn(context["reference"], str(caught.exception))
            self.assertIn("technisch", str(caught.exception))

    def test_unfinished_step_reason_is_available_only_in_diagnostics(self):
        with patch("completion.reply", return_value=json.dumps({
            "step_complete": False, "reason": "private: tutor confirmation missing",
        })), patch("completion.record") as record, self.assertLogs(
            "minimal_chat.completion", level="INFO"
        ) as logs, diagnostics.diagnostic_scope() as context:
            self.assertFalse(step_complete([], "draft", "current requirements", "PIA"))
            self.assertEqual(record.call_args.kwargs["reason"], "private: tutor confirmation missing")
            self.assertNotIn("completion_error", context)
            self.assertNotIn("private", "\n".join(logs.output))

    def test_failed_file_write_does_not_break_chat_or_log_model_text(self):
        with patch.dict(os.environ, {"AILA_DIAGNOSTICS": "1"}), patch.object(
            Path, "open", side_effect=OSError("private")
        ), self.assertLogs("minimal_chat.diagnostics", level="WARNING") as logs:
            diagnostics.record("test", "reference", draft="private draft")
        self.assertIn("reference=reference", "\n".join(logs.output))
        self.assertNotIn("private", "\n".join(logs.output))

    def test_nested_contexts_do_not_leak_between_requests(self):
        with diagnostics.diagnostic_scope(task_title="outer") as outer:
            with diagnostics.diagnostic_scope(task_title="inner") as inner:
                self.assertEqual(diagnostics.reference(), inner["reference"])
            self.assertEqual(diagnostics.reference(), outer["reference"])
        self.assertNotEqual(diagnostics.reference(), outer["reference"])


if __name__ == "__main__":
    unittest.main()
