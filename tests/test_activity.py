from copy import deepcopy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import academic
import session_store
from activity import ACTIVITY_FILE, IMAGE, advance, load_activity, system_prompt, enter_task, start_conversation


class ActivityFlowTest(unittest.TestCase):
    def setUp(self):
        completion = patch("completion.step_complete", return_value=True)
        completion.start()
        self.addCleanup(completion.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        patcher = patch.object(session_store, "DB_PATH", Path(temp.name) / "sessions.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)
        # UI progression tests isolate generation; guardrail behavior has its own tests.
        patcher = patch("guardrail.guarded_reply", side_effect=lambda messages, prompt, **kwargs: academic.reply(messages, prompt))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_activity_flow(self):
        fixture = deepcopy(load_activity())
        fixture["tasks"] = fixture["tasks"][:2]
        fixture["tasks"][1]["intro_sequence"] = ["robot_and_battery_01.md", "robot_and_battery_02.md"]
        fixture["tasks"][1]["conversation"] = [
            {"message": "Bereite dich vor", "type": "bold", "action": "no_wait"},
            {"message": "./figures/intro_robot_small.png", "type": "image", "action": "no_wait"},
            {"message": "Problemformulierung"},
        ]
        patcher = patch("activity.load_activity", return_value=fixture)
        patcher.start()
        self.addCleanup(patcher.stop)
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        from study_flow import initial_activity_state
        token = session_store.SessionStore().create(fixture, initial_activity_state())
        app = AppTest.from_file(str(app_path), default_timeout=10)
        app.query_params["session"] = token
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(len(app.chat_input), 0)
        intro = (ACTIVITY_FILE.parent / load_activity()["intro_sequence"]).read_text(encoding="utf-8")
        self.assertEqual(len(app.get("imgs")), len(IMAGE.findall(intro)))
        self.assertEqual([b.key for b in app.button], ["start_activity"])

        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.subheader[0].value, "Willkommen!")
        self.assertEqual(len(app.chat_message), 1)
        self.assertEqual(len(app.chat_input), 1)
        self.assertEqual([b.key for b in app.main.button], ["open_intro"])
        app.run()
        self.assertEqual(len(app.chat_message), 1)

        response = Mock()
        response.json.return_value = {"data": {"content": "Hallo!"}}
        secrets = {"ACADEMIC_AI_CLIENT_ID": "test", "ACADEMIC_AI_CLIENT_SECRET": "test"}
        with patch.object(academic.st, "secrets", secrets), patch.object(
            academic.requests, "post", return_value=response
        ) as post:
            app.chat_input[0].set_value("Ich bin Alex.").run()
            self.assertFalse(app.exception)
            payload = post.call_args.kwargs["json"]
            self.assertEqual(payload["model"], academic.MODEL.partition(":")[2])
            description = (fixture.get("role_description") or "").strip()
            if description:
                self.assertIn(description, payload["messages"][-1]["content"])
                self.assertFalse(any(description in m.value for m in app.markdown))
            self.assertIn("Warte auf die", payload["messages"][-1]["content"])
            self.assertTrue(all(set(m) == {"role", "content"} for m in payload["messages"]))
            self.assertFalse(any("Warte auf die" in m.value for m in app.markdown))
            state = app.session_state["activity_state"]
            self.assertEqual(state["messages"][1]["content"], "Ich bin Alex.")
            app.run()
            self.assertEqual(len(app.chat_message), 3)
            self.assertEqual(len(app.chat_input), 0)
            self.assertEqual([b.key for b in app.main.button], ["open_intro", "next_task"])
            returning = AppTest.from_file(str(app_path), default_timeout=10)
            returning.query_params["session"] = app.query_params["session"]
            returning.run()
            self.assertFalse(returning.exception)
            self.assertEqual(len(returning.chat_message), 3)
            self.assertEqual(len(returning.chat_input), 0)
            self.assertEqual([b.key for b in returning.main.button], ["open_intro", "next_task"])

            app.button(key="next_task").click().run()
            self.assertEqual(app.session_state["activity_state"]["task_index"], 0)
            app.button(key="confirm_next_task_yes").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.sidebar.subheader[0].value, "Problemformulierung")
            self.assertEqual(len(app.chat_input), 0)
            self.assertEqual(len(app.chat_message), 3)
            self.assertEqual(len(app.expander), 3)
            self.assertTrue(app.button(key="intro_back").disabled)
            app.button(key="intro_next").click().run()
            saved_intro = AppTest.from_file(str(app_path), default_timeout=10)
            saved_intro.query_params["session"] = app.query_params["session"]
            saved_intro.run()
            self.assertEqual(saved_intro.session_state["activity_state"]["intro_page"], 1)
            self.assertEqual(len(saved_intro.chat_input), 0)
            app.button(key="intro_back").click().run()
            self.assertEqual(app.session_state["activity_state"]["intro_page"], 0)
            app.button(key="intro_next").click().run()
            app.button(key="confirm_intro").click().run()
            self.assertEqual(len(app.chat_message), 4)
            self.assertEqual([h.value for h in app.main.subheader],
                             ["Willkommen!", "Problemformulierung"])
            timeline = [element.type for element in app.main
                        if element.type in {"subheader", "chat_message"}]
            self.assertEqual(timeline, ["subheader", "chat_message", "chat_message",
                                        "chat_message", "subheader", "chat_message"])
            self.assertTrue(any(m.value.startswith("**") for m in app.markdown))
            self.assertTrue(any("Ich bin Alex." in m.value for m in app.markdown))
            self.assertEqual(app.session_state["activity_state"]["task_index"], 1)
            self.assertEqual(len(app.main.get("imgs")), 1)
            self.assertEqual(len(app.chat_input), 1)
            app.run()
            self.assertEqual(len(app.chat_message), 4)
            before = len(app.session_state["activity_state"]["messages"])
            calls_before = post.call_count
            app.button(key="open_intro").click().run()
            self.assertEqual(len(app.chat_input), 1)
            self.assertEqual(app.session_state["activity_state"]["intro_page"], 1)
            review = AppTest.from_file(str(app_path), default_timeout=10)
            review.query_params["session"] = app.query_params["session"]
            review.run()
            self.assertEqual(review.session_state["activity_state"]["intro_page"], 1)
            self.assertEqual(len(review.chat_input), 1)
            app.button(key="close_intro").click().run()
            self.assertEqual(len(app.session_state["activity_state"]["messages"]), before)
            self.assertEqual(post.call_count, calls_before)


            post.side_effect = requests.Timeout
            app.chat_input[0].set_value("Ein Versuch").run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.error), 1)
            self.assertIn("120 Sekunden", app.error[0].value)
            self.assertEqual(len(app.session_state["activity_state"]["messages"]), before)

            post.side_effect = None
            app.chat_input[0].set_value("Meine Antwort").run()
            self.assertFalse(app.exception)
            self.assertNotIn("Warte auf die", post.call_args.kwargs["json"]["messages"][-1]["content"])
            sent = post.call_args.kwargs["json"]["messages"]
            if description:
                self.assertIn(description, sent[-1]["content"])
            self.assertEqual([m["role"] for m in sent], ["assistant", "user", "assistant", "user"])
            self.assertIn("Bereite dich vor", sent[2]["content"])
            self.assertIn("intro_robot_small.png", sent[2]["content"])
            self.assertIn("Problemformulierung", sent[2]["content"])
            app.run()
            self.assertEqual(len(app.chat_message), 6)
            resumed = AppTest.from_file(str(app_path), default_timeout=10)
            resumed.query_params["session"] = app.query_params["session"]
            resumed.run()
            self.assertFalse(resumed.exception)
            self.assertEqual([h.value for h in resumed.main.subheader],
                             ["Willkommen!", "Problemformulierung"])
            self.assertEqual(len(resumed.chat_message), 6)
            self.assertTrue(any("Ich bin Alex." in m.value for m in resumed.markdown))
            self.assertEqual(resumed.session_state["activity_state"], app.session_state["activity_state"])

            self.assertEqual(len(app.chat_input), 1)
            self.assertEqual([b.key for b in app.main.button], ["open_intro", "finish_activity"])

    def task_view(self, intro_files, legacy=False):
        activity = deepcopy(load_activity())
        task = activity["tasks"][1]
        task["intro_sequence"] = intro_files
        task["conversation"] = [
            {"message": "First", "action": "no_wait"},
            {"message": "Second", "action": "no_wait"},
            {"message": "Third"},
        ]
        state = {"started": True, "task_index": 1, "next_message": 0,
                 "action": "wait", "messages": [], "task_start": 0, "answered": False}
        if legacy:
            advance(state, task)
        else:
            enter_task(state, task)
        token = session_store.SessionStore().create(activity, state)
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
        app.query_params["session"] = token
        return app.run()

    def test_single_intro_and_legacy_sessions(self):
        files = ["robot_and_battery_02.md"]
        app = self.task_view(files)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.chat_input), 0)
        self.assertTrue(app.button(key="intro_back").disabled)
        app.button(key="confirm_intro").click().run()
        self.assertEqual(len(app.chat_input), 1)
        self.assertEqual(len(app.session_state["activity_state"]["messages"]), 3)
        legacy = self.task_view(files, legacy=True)
        self.assertFalse(legacy.exception)
        self.assertEqual(len(legacy.chat_input), 1)
        self.assertEqual(len(legacy.session_state["activity_state"]["messages"]), 3)

    def test_missing_intro_blocks_start_but_review_can_return(self):
        app = self.task_view(["missing-intro-for-test.md"])
        self.assertFalse(app.exception)
        self.assertIn("missing-intro-for-test.md", app.error[0].value)
        self.assertTrue(app.button(key="confirm_intro").disabled)
        self.assertEqual(len(app.chat_input), 0)
        legacy = self.task_view(["missing-intro-for-test.md"], legacy=True)
        legacy.button(key="open_intro").click().run()
        self.assertEqual(len(legacy.error), 1)
        legacy.button(key="close_intro").click().run()
        self.assertEqual(len(legacy.chat_input), 1)

    def test_no_intro_starts_immediately_and_start_is_idempotent(self):
        for extras in ({}, {"intro_sequence": []}):
            task = {"conversation": [{"message": "Hello"}], **extras}
            state = {"messages": []}
            enter_task(state, task)
            self.assertTrue(state["conversation_started"])
            self.assertEqual(len(state["messages"]), 1)
            start_conversation(state, task)
            self.assertEqual(len(state["messages"]), 1)
        app = self.task_view([])
        self.assertEqual(len(app.chat_input), 1)
        self.assertFalse(any(b.key == "open_intro" for b in app.button))

    def test_user_initiates_after_intro_and_hidden_context_reaches_model(self):
        activity = deepcopy(load_activity())
        task = activity["tasks"][1]
        task["intro_sequence"] = ["robot_and_battery_02.md"]
        task["conversation"] = [{"system_info": "Listen to the learner explanation."}]
        state = {"started": True, "task_index": 1, "messages": []}
        enter_task(state, task)
        token = session_store.SessionStore().create(activity, state)
        app_path = str(Path(__file__).resolve().parents[1] / "app.py")
        app = AppTest.from_file(app_path)
        app.query_params["session"] = token
        with patch("academic.reply", return_value="Have I understood correctly?") as reply:
            app.run()
            app.button(key="confirm_intro").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.chat_message), 0)
            self.assertEqual(len(app.chat_input), 1)
            reply.assert_not_called()
            resumed = AppTest.from_file(app_path)
            resumed.query_params["session"] = token
            resumed.run()
            self.assertEqual(len(resumed.chat_message), 0)
            self.assertEqual(len(resumed.chat_input), 1)
            app.chat_input[0].set_value("Here is my explanation.").run()
            self.assertFalse(app.exception)
            reply.assert_called_once()
            self.assertIn("Listen to the learner explanation.", reply.call_args.args[1])
            self.assertEqual(reply.call_args.args[0], [{"role": "user", "content": "Here is my explanation."}])
            self.assertFalse(any("Listen to the learner explanation." in m.value for m in app.markdown))
            self.assertEqual(len(app.session_state["activity_state"]["messages"]), 2)

    def test_missing_or_empty_message_is_a_silent_wait(self):
        for entry in ({}, {"system_info": "Hidden"}, {"message": ""},
                      {"message": None}, {"message": "   "}):
            with self.subTest(entry=entry):
                task = {"conversation": [entry, {"message": "After response"}]}
                state = {"messages": []}
                enter_task(state, task)
                self.assertEqual(state["messages"], [])
                self.assertEqual(state["next_message"], 1)
                self.assertEqual(state["action"], "wait")
                advance(state, task)
                self.assertEqual(state["messages"][0]["content"], "After response")
        state = {"messages": []}
        enter_task(state, {"conversation": [
            {"system_info": "Hidden", "action": "no_wait"},
            {"message": "Visible"},
        ]})
        self.assertEqual(len(state["messages"]), 1)
        self.assertEqual(state["next_message"], 2)

    def test_role_framework_is_activity_specific_and_precedes_task_instructions(self):
        task = {"task_title": "Task", "system_info": "Task guidance", "conversation": [
            {"system_info": "Current guidance"},
            {"system_info": "Future guidance"},
        ]}
        activity = {"role": "AILA", "role_description": "Act as a curious learner."}
        prompt = system_prompt(activity, task, 1)
        self.assertIn(activity["role_description"], prompt)
        self.assertLess(prompt.index(activity["role_description"]), prompt.index("Task guidance"))
        self.assertIn("Current guidance", prompt)
        self.assertNotIn("Future guidance", prompt)
        changed = system_prompt({"role": "Other", "role_description": "Act as a tutor."}, task, 1)
        self.assertIn("Act as a tutor.", changed)
        self.assertNotIn(activity["role_description"], changed)
        self.assertIn("Agent name: AILA.", system_prompt({"role": "AILA"}, task, 1))

    def test_waiting_steps_do_not_skip_user_input(self):
        task = {"conversation": [
            {"message": "First"},
            {"message": "Second", "action": "no_wait"},
            {"message": "Third"},
        ]}
        state = {"messages": [], "next_message": 0, "answered": True}
        advance(state, task)
        self.assertEqual([m["content"] for m in state["messages"]], ["First"])
        self.assertFalse(state["answered"])
        state["answered"] = True
        advance(state, task)
        self.assertEqual([m["content"] for m in state["messages"]], ["First", "Second", "Third"])
        self.assertFalse(state["answered"])
        state["answered"] = True
        advance(state, task)
        self.assertTrue(state["answered"])
        self.assertEqual(len(state["messages"]), 3)


if __name__ == "__main__":
    unittest.main()
