from copy import deepcopy
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import session_store
from activity import enter_task, load_activity


APP = str(Path(__file__).resolve().parents[1] / "app.py")


class CompletionTest(unittest.TestCase):
    def setUp(self):
        completion = patch("completion.step_complete", return_value=True)
        completion.start()
        self.addCleanup(completion.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patcher = patch.object(session_store, "DB_PATH", Path(temporary.name) / "sessions.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)
        import academic
        patcher = patch("guardrail.guarded_reply", side_effect=lambda messages, prompt, **kwargs: academic.reply(messages, prompt))
        patcher.start()
        self.addCleanup(patcher.stop)

    def create_app(self, task, later_tasks=None):
        activity = deepcopy(load_activity())
        activity["tasks"] = [task] + (later_tasks or [])
        state = {"started": True, "task_index": 0, "messages": [
            {"role": "user", "content": "Earlier conversation"},
            {"role": "assistant", "content": "Earlier reply"},
        ]}
        enter_task(state, task)
        token = session_store.SessionStore().create(activity, state)
        app = AppTest.from_file(APP, default_timeout=10)
        app.query_params["session"] = token
        return app.run()

    def test_intro_only_completion_saved_and_celebrates_once(self):
        app = self.create_app({"task_title": "Last task", "intro_sequence": ["robot_and_battery_02.md"]})
        self.assertFalse(app.exception)
        self.assertEqual(app.button(key="confirm_intro").label, "Fertig")
        self.assertFalse(app.chat_input)
        with patch("presentation.celebrate") as celebrate:
            app.button(key="confirm_intro").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.session_state["activity_state"]["completed"])
            self.assertEqual(app.success[0].value, "Fertig!")
            self.assertEqual(len(app.chat_message), 2)
            self.assertFalse(app.chat_input)
            celebrate.assert_called_once()
            app.run()
            self.assertEqual(celebrate.call_count, 1)
            resumed = AppTest.from_file(APP, default_timeout=10)
            resumed.query_params["session"] = app.query_params["session"]
            resumed.run()
            self.assertTrue(resumed.session_state["activity_state"]["completed"])
            self.assertEqual(len(resumed.chat_message), 2)
            self.assertFalse(resumed.chat_input)
            self.assertEqual(celebrate.call_count, 1)
            resumed.button(key="open_intro").click().run()
            self.assertFalse(any(b.key == "confirm_intro" for b in resumed.button))
            resumed.button(key="close_intro").click().run()
            self.assertEqual(resumed.success[0].value, "Fertig!")
            self.assertEqual(celebrate.call_count, 1)

    def test_intermediate_intro_only_advances_without_chat(self):
        app = self.create_app(
            {"task_title": "Instructions", "intro_sequence": ["robot_and_battery_02.md"], "conversation": []},
            [{"task_title": "Next task", "conversation": [{"system_info": "Wait for user"}]}],
        )
        self.assertFalse(app.button(key="confirm_intro").disabled)
        app.button(key="confirm_intro").click().run()
        self.assertEqual(app.session_state["activity_state"]["task_index"], 0)
        app.button(key="confirm_next_task_yes").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["activity_state"]["task_index"], 1)
        self.assertFalse(app.session_state["activity_state"]["completed"])
        self.assertEqual(len(app.chat_input), 1)
        self.assertFalse(any(b.key == "finish_activity" for b in app.button))

    def test_final_user_initiated_task_requires_successful_exchange(self):
        app = self.create_app({"task_title": "Dialogue", "conversation": [{"system_info": "Wait"}]})
        self.assertFalse(any(b.key == "finish_activity" for b in app.button))
        import streamlit as st
        with patch("academic.reply", return_value="Response"), patch(
            "streamlit.spinner", wraps=st.spinner
        ) as spinner, patch("presentation.scroll_to_latest") as scroll:
            app.chat_input[0].set_value("My answer").run()
            spinner.assert_called_once_with("AILA denkt nach \u2026", show_time=True)
            self.assertEqual(scroll.call_count, 2)
            app.run()
            self.assertEqual(scroll.call_count, 2)
        self.assertFalse(app.exception)
        self.assertEqual(app.button(key="finish_activity").label, "Fertig")
        with patch("presentation.celebrate") as celebrate:
            app.button(key="finish_activity").click().run()
            self.assertFalse(app.chat_input)
            self.assertEqual(len(app.session_state["activity_state"]["messages"]), 4)
            celebrate.assert_called_once()

    def test_next_task_requires_confirmation_and_cancel_preserves_progress(self):
        app = self.create_app(
            {"task_title": "Current", "conversation": [{"message": "Done", "action": "continue"}]},
            [{"task_title": "Next", "conversation": [{"message": "Next message"}]}],
        )
        before = deepcopy(app.session_state["activity_state"])
        app.button(key="next_task").click().run()
        self.assertTrue(any(m.value == "Hast du diesen Abschnitt mit AILA abgeschlossen und möchtest zum nächsten Thema gelangen?"
                            for m in app.markdown))
        self.assertEqual(app.session_state["activity_state"], before)
        app.button(key="confirm_next_task_no").click().run()
        self.assertEqual(app.session_state["activity_state"], before)
        self.assertFalse(any(b.key == "confirm_next_task_yes" for b in app.button))
        app.button(key="next_task").click().run()
        app.button(key="confirm_next_task_yes").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["activity_state"]["task_index"], 1)
        token = app.query_params["session"][0]
        self.assertEqual(session_store.SessionStore().load(token)[1]["task_index"], 1)

    def test_failed_save_does_not_complete_or_celebrate(self):
        app = self.create_app({"task_title": "Done", "conversation": []})
        token = app.query_params["session"][0]
        with patch.object(session_store.SessionStore, "save", side_effect=sqlite3.OperationalError("disk full")), patch(
            "presentation.celebrate"
        ) as celebrate:
            app.button(key="finish_activity").click().run()
            self.assertTrue(app.error)
            celebrate.assert_not_called()
        self.assertFalse(session_store.SessionStore().load(token)[1].get("completed", False))
        app.run()
        self.assertEqual(app.button(key="finish_activity").label, "Fertig")

    def test_sidebar_keeps_chat_visible_and_information_toggles(self):
        import presentation
        with patch("presentation.control_sidebar") as sidebar:
            app = self.create_app({"task_title": "Task", "intro_sequence": ["robot_and_battery_02.md"],
                                   "conversation": [{"system_info": "Wait"}]})
            sidebar.assert_called_with("open")
            self.assertEqual(len(app.sidebar.subheader), 1)
            self.assertEqual(len(app.main.chat_message), 2)
            self.assertFalse(app.chat_input)
            app.button(key="confirm_intro").click().run()
            sidebar.assert_called_with("close")
            docks = [block for block in app.get("flex_container") if block.proto.id.endswith("-chat_dock")]
            self.assertEqual(len(docks), 1)
            self.assertEqual(len(docks[0].chat_input), 1)
            self.assertEqual(docks[0].button[0].key, "open_intro")
            before = deepcopy(app.session_state["activity_state"])
            app.button(key="open_intro").click().run()
            sidebar.assert_called_with("toggle")
            self.assertEqual(len(app.chat_input), 1)
            self.assertEqual(len(app.main.chat_message), 2)
            self.assertEqual(app.session_state["activity_state"], before)
            app.button(key="open_intro").click().run()
            sidebar.assert_called_with("toggle")
            app.button(key="close_intro").click().run()
            sidebar.assert_called_with("close")
            calls = sidebar.call_count
            app.run()
            self.assertEqual(sidebar.call_count, calls)

    def test_theme_styles_and_reduced_motion_celebration(self):
        from types import SimpleNamespace
        import presentation
        for theme, background in (("light", "#ffffff"), ("dark", "#0e1117")):
            with self.subTest(theme=theme), patch.object(presentation.st, "context", SimpleNamespace(
                theme=SimpleNamespace(type=theme)
            )), patch.object(presentation.st, "get_option", return_value=None), patch.object(
                presentation.st, "html"
            ) as html:
                presentation.page_style(intro=True)
                css = html.call_args.args[0]
                self.assertIn(background, css)
                self.assertIn("max-width: 480px", css)
                self.assertIn("padding-bottom:", css)
        with patch.object(presentation.st, "html") as html:
            presentation.celebrate()
            content = html.call_args.args[0]
            self.assertIn("prefers-reduced-motion: reduce", content)
            self.assertIn("pointer-events:none", content)
            self.assertIn('aria-hidden="true"', content)
            self.assertNotIn("<script", content)

    def test_repeated_sidebar_commands_have_distinct_scripts_after_html_sanitizing(self):
        import re
        import presentation
        with patch.object(presentation.st, "html") as html:
            presentation.control_sidebar("toggle")
            first = re.sub(r"<!--.*?-->", "", html.call_args.args[0], flags=re.DOTALL)
            presentation.control_sidebar("toggle")
            second = re.sub(r"<!--.*?-->", "", html.call_args.args[0], flags=re.DOTALL)
        self.assertNotEqual(first, second)
        self.assertIn("// sidebar-event-", first)

    def test_final_continue_action_and_missing_conversation(self):
        for task in (
            {"task_title": "Final", "conversation": [{"message": "All done", "action": "continue"}]},
            {"task_title": "Final"},
        ):
            with self.subTest(task=task):
                app = self.create_app(task)
                self.assertFalse(app.exception)
                self.assertFalse(app.chat_input)
                self.assertEqual(app.button(key="finish_activity").label, "Fertig")
                self.assertFalse(app.session_state["activity_state"]["completed"])


if __name__ == "__main__":
    unittest.main()
