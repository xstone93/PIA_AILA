"""Check responsibility boundaries without prescribing prompt wording."""
import json
import unittest
from unittest.mock import patch

from activity import system_prompt, pia_assessment_context
from guardrail import guarded_reply, TASK_SCOPE
from pia_prompts import REPLY_RULES, ASSESSMENT_RULES, VALIDATION_RULES
from completion import step_complete


class PiaPromptRoutingTest(unittest.TestCase):
    def test_generation_uses_pia_policy_and_prescribed_content_once(self):
        task = {"task_title": "Example", "system_info": "TASK REQUIREMENT", "conversation": [
            {"message": "First question", "system_info": "OLD REQUIREMENT"},
            {"message": "Current question", "system_info": "CURRENT REQUIREMENT"},
            {"message": "Future question", "system_info": "FUTURE REQUIREMENT"},
        ]}
        context = system_prompt({"role": "PIA", "role_framework": "PRESCRIBED ROLE"}, task, 2)
        with patch("guardrail.reply", side_effect=["Feedback", '{"allowed":true,"violations":[]}']) as request:
            guarded_reply([{"role": "user", "content": "Answer"}], context, "PIA")
        prompt = request.call_args_list[0].args[1]
        self.assertEqual(prompt.count(REPLY_RULES), 1)
        for content in ("PRESCRIBED ROLE", "TASK REQUIREMENT", "CURRENT REQUIREMENT"):
            self.assertEqual(prompt.count(content), 1)
        for content in ("OLD REQUIREMENT", "FUTURE REQUIREMENT", TASK_SCOPE, ASSESSMENT_RULES):
            self.assertNotIn(content, prompt)
        self.assertEqual(request.call_args_list[1].args[1], VALIDATION_RULES)

    def test_assessment_has_own_policy_without_reply_instructions(self):
        context = pia_assessment_context({"task_title": "Example", "conversation": [
            {"message": "Explain why", "system_info": "Expected reasoning"},
        ]}, 1)
        with patch("completion.reply", return_value=json.dumps({"reason": "Missing", "criteria": [
            {"id": "reason", "requirement": "Explain why", "status": "missing", "evidence": []},
        ]})) as request:
            self.assertFalse(step_complete([{"role": "user", "content": "Unsure"}], context, "PIA"))
        self.assertEqual(request.call_args.args[1], ASSESSMENT_RULES)
        self.assertNotIn(REPLY_RULES, request.call_args.args[0][0]["content"])


if __name__ == "__main__":
    unittest.main()
