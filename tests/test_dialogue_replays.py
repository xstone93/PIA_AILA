import unittest

from dialogue_cases import CASES, CORPUS
from dialogue_runner import run_dialogue, check_language


class DialogueReplayTest(unittest.TestCase):
    def test_all_curated_dialogues(self):
        for case in CASES:
            with self.subTest(case=case["id"]):
                report = run_dialogue(case)
                self.assertEqual(report["status"], "passed", report)

    def test_all_six_pilot_protocols_are_represented(self):
        sources = {action["source"] for case in CASES for action in case["actions"] if action["action"] == "say"}
        self.assertTrue({record["source"] for record in CORPUS}.issubset(sources))
        self.assertEqual(len(CORPUS), 6)
        self.assertNotIn("daniel", str(CORPUS).lower())

    def test_known_bad_replies_are_not_treated_as_expected_behavior(self):
        for reply, complete in (("Hallo Alex! Das stimmt.", True),
                                ("Ich bleibe bei unserer Aufgabe. Das stimmt.", True),
                                ("Das stimmt. Welche Regeln fehlen noch?", True)):
            with self.subTest(reply=reply), self.assertRaises(AssertionError):
                check_language({}, "PIA", reply, complete)


if __name__ == "__main__":
    unittest.main()
