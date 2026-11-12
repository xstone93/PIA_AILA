import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import academic


class AcademicErrorsTest(unittest.TestCase):
    def test_consecutive_scripted_messages_form_one_api_turn(self):
        from copy import deepcopy

        messages = [
            {"role": "assistant", "content": "Welcome"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Reply"},
            {"role": "assistant", "content": "Continue"},
            {"role": "assistant", "content": "Task heading", "type": "bold"},
            {"role": "assistant", "content": "./figures/example.png", "type": "image"},
            {"role": "assistant", "content": "Task question"},
            {"role": "user", "content": "My answer", "timestamp": "2026-11-12T09:00:00+00:00"},
        ]
        original = deepcopy(messages)
        response = Mock()
        response.json.return_value = {"data": {"content": "Response"}}
        secrets = {"ACADEMIC_AI_CLIENT_ID": "test", "ACADEMIC_AI_CLIENT_SECRET": "secret"}
        with patch.object(academic.st, "secrets", secrets), patch.object(
            academic.requests, "post", return_value=response
        ) as post:
            self.assertEqual(academic.reply(messages, "Hidden instructions"), "Response")
        sent = post.call_args.kwargs["json"]["messages"]
        self.assertEqual([m["role"] for m in sent], ["assistant", "user", "assistant", "user"])
        self.assertEqual(sent[2]["content"], "\n\n".join(m["content"] for m in original[2:7]))
        self.assertEqual(sent[-1]["content"], "[Instructions: Hidden instructions]\n\nMy answer")
        self.assertEqual(messages, original)
        self.assertTrue(all(set(m) == {"role", "content"} for m in sent))

    def test_response_failures_are_distinguishable(self):
        cases = [
            ({"data": {"content": ""}}, "leere Antwort"),
            ({"data": {"content": "   "}}, "leere Antwort"),
            ({"data": {"content": None}}, "leere Antwort"),
            ({"data": {"content": []}}, "kein Text"),
            ({"data": None}, "data.content"),
            ({}, "data.content"),
            ([], "data.content"),
        ]
        secrets = {"ACADEMIC_AI_CLIENT_ID": "test", "ACADEMIC_AI_CLIENT_SECRET": "secret"}
        for payload, expected in cases:
            with self.subTest(payload=payload):
                response = Mock()
                response.json.return_value = payload
                with patch.object(academic.st, "secrets", secrets), patch.object(
                    academic.requests, "post", return_value=response
                ):
                    with self.assertRaises(academic.AcademicAIResponseError) as caught:
                        academic.reply([{"role": "user", "content": "Test"}])
                    self.assertIn(expected, academic.error_message(caught.exception))

    def test_non_json_response(self):
        response = Mock()
        response.json.side_effect = ValueError("private response body")
        secrets = {"ACADEMIC_AI_CLIENT_ID": "test", "ACADEMIC_AI_CLIENT_SECRET": "secret"}
        with patch.object(academic.st, "secrets", secrets), patch.object(
            academic.requests, "post", return_value=response
        ):
            with self.assertRaises(academic.AcademicAIResponseError) as caught:
                academic.reply([{"role": "user", "content": "Test"}])
            self.assertIn("JSON", academic.error_message(caught.exception))
            self.assertNotIn("private", academic.error_message(caught.exception))

    def test_http_status_and_timeout_do_not_expose_raw_errors(self):
        for status in (400, 401, 403, 429, 500, 502):
            with self.subTest(status=status):
                response = requests.Response()
                response.status_code = status
                error = requests.HTTPError("private response body", response=response)
                message = academic.error_message(error)
                self.assertIn(str(status), message)
                self.assertNotIn("private", message)
        self.assertIn("120 Sekunden", academic.error_message(requests.Timeout()))
        self.assertIn("Verbindung", academic.error_message(requests.ConnectionError("private")))
        self.assertIn("Zugangsdaten fehlen", academic.error_message(KeyError("private")))


if __name__ == "__main__":
    unittest.main()
