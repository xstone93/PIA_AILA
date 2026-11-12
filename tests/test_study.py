from copy import deepcopy
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import academic
import content_registry as registry
import guardrail
import session_store
import study_flow as flow
from activity import system_prompt
from chat_export import chat_markdown

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def ready_snapshot():
    """Test-only ready activities; never change production draft files."""
    snapshot = flow.load_study()
    snapshot["errors"] = {}
    for sequence in flow.GROUPS.values():
        for activity_id in sequence:
            activity = registry.load_activity(activity_id)
            activity["status"] = "ready"
            activity["tasks"] = [{"task_title": "Testabschnitt", "conversation": [{"system_info": "Test guidance"}]}]
            snapshot["activities"][activity_id] = activity
            snapshot["checkpoints"][activity_id] = {"text": "Nachbefragung", "survey_url": "https://example.org/survey"}
    snapshot["checkpoints"]["pre_study"] = {"text": "Vorbefragung", "survey_url": "https://example.org/pre"}
    return snapshot


class StudyFlowTest(unittest.TestCase):
    def test_group_sequences_and_final_gate(self):
        snapshot = ready_snapshot()
        for group, sequence in flow.GROUPS.items():
            state = flow.initial_study_state()
            state["phase"] = "enrollment"
            state = flow.enroll(snapshot, state, group, " AbC-12 ")
            self.assertEqual(state["participant_code"], "AbC-12")
            self.assertEqual(state["phase"], "pre_survey")
            state = flow.confirm_checkpoint(snapshot, state)
            for index, activity_id in enumerate(sequence):
                self.assertEqual(flow.current_activity_id(snapshot, state), activity_id)
                self.assertEqual(state["phase"], "activity")
                self.assertEqual(state["activities"][activity_id]["messages"], [])
                with self.assertRaises(ValueError):
                    flow.confirm_checkpoint(snapshot, state)
                progress = deepcopy(state["activities"][activity_id])
                progress.update(completed=True, messages=[{"role": "user", "content": f"Conversation {index}"}])
                state = flow.save_activity_progress(snapshot, state, progress)
                self.assertEqual(state["phase"], "post_survey")
                state = flow.confirm_checkpoint(snapshot, state)
            self.assertEqual(state["phase"], "completed")
            self.assertEqual(len(state["activities"]), 2)
            self.assertEqual(len(state["checkpoints"]), 3)
            self.assertTrue(all(c["verification"] == "self_reported" for c in state["checkpoints"].values()))

    def test_enrollment_required_locked_and_unready(self):
        snapshot = ready_snapshot()
        state = flow.initial_study_state()
        state["phase"] = "enrollment"
        for group, code in ((None, "abc"), ("C", "abc"), ("A", " ")):
            with self.assertRaises(ValueError):
                flow.enroll(snapshot, state, group, code)
        enrolled = flow.enroll(snapshot, state, "A", "abc")
        with self.assertRaises(ValueError):
            flow.enroll(snapshot, enrolled, "B", "def")
        with self.assertRaises(ValueError):
            flow.enroll(flow.load_study(), state, "A", "abc")
        self.assertIsNone(state["group"])

    def test_real_content_readiness_and_relative_paths(self):
        registry.validate_activity(registry.load_activity())
        registry.validate_activity(registry.load_activity("pia_cables_and_tester"))
        for activity_id in ("pia_robot_and_batteries", "aila_cables_and_tester"):
            with self.assertRaises(ValueError):
                registry.validate_activity(registry.load_activity(activity_id))
        broken = registry.load_activity()
        broken["tasks"][0]["intro_sequence"] = ["missing.md"]
        with self.assertRaisesRegex(ValueError, "missing.md"):
            registry.validate_activity(broken)
        with self.assertRaisesRegex(ValueError, "außerhalb"):
            registry.local_file(registry.CONTENT_ROOT, "../app.py")

    def test_missing_survey_and_optional_markdown(self):
        config = json.loads(flow.CONFIG_FILE.read_text(encoding="utf-8"))
        for checkpoint in [config["pre_study"], *config["post_activity"].values()]:
            checkpoint.update(survey_url="https://example.org/survey", markdown=None)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with patch.object(flow, "CONFIG_FILE", path):
                snapshot = flow.load_study()
                self.assertEqual(snapshot["checkpoints"]["pre_study"]["text"], "")
            config["pre_study"]["survey_url"] = "javascript:alert(1)"
            path.write_text(json.dumps(config), encoding="utf-8")
            with patch.object(flow, "CONFIG_FILE", path):
                self.assertIn("pre_study", flow.load_study()["errors"])


class StudyPersistenceTest(unittest.TestCase):
    def test_additive_migration_metadata_duplicates_and_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sessions.sqlite3"
            with closing(sqlite3.connect(path)) as connection:
                with connection:
                    connection.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, activity TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)")
                    connection.execute("INSERT INTO sessions (id,activity,state) VALUES (?,?,?)", ("a" * 43, '{"role":"AILA"}', '{"started":false}'))
            store = session_store.SessionStore(path)
            self.assertEqual(store.load("a" * 43)[0], {"role": "AILA"})
            snapshot = ready_snapshot()
            state = flow.initial_study_state()
            state["phase"] = "enrollment"
            state = flow.enroll(snapshot, state, "B", "SameCode")
            tokens = [store.create(snapshot, state), store.create(snapshot, state)]
            self.assertNotEqual(*tokens)
            snapshot["config"]["version"] = "changed"
            for phase in ("pre_survey", "activity", "post_survey", "completed"):
                current = deepcopy(state)
                current["phase"] = phase
                revision = store.load(tokens[0])[2]
                store.save(tokens[0], current, revision)
                restored, saved, _ = session_store.SessionStore(path).load(tokens[0])
                self.assertEqual(saved, current)
                self.assertEqual(restored["config"]["version"], "1")
            with store.connect() as connection:
                rows = connection.execute("SELECT study_group, participant_code, study_version FROM sessions WHERE participant_code = 'SameCode'").fetchall()
            self.assertEqual(rows, [("B", "SameCode", "1")] * 2)
            changed = deepcopy(state)
            changed["participant_code"] = "Other"
            with self.assertRaises(ValueError):
                store.save(tokens[0], changed, store.load(tokens[0])[2])


class RoleTest(unittest.TestCase):
    def test_roles_and_fail_closed_validation(self):
        task = {"task_title": "Example"}
        for role in ("PIA", "AILA"):
            activity = registry.load_activity(role.lower() + "_robot_and_batteries")
            prompt = system_prompt(activity, task, 0)
            self.assertIn(f"Agent name: {role}", prompt)
            self.assertEqual("als lernende Studentin" in prompt, role == "AILA")
            with patch("guardrail.reply", side_effect=["Draft", '{"allowed":true,"violations":[]}']) as reply:
                self.assertEqual(guardrail.guarded_reply([], prompt, role=role), "Draft")
                if role == "PIA":
                    self.assertEqual(reply.call_args_list[1].args[1], guardrail.PIA_VALIDATOR_PROMPT)
                else:
                    reply.assert_called_once()
            if role == "PIA":
                with patch("guardrail.reply", side_effect=["Draft", "invalid JSON"]):
                    with self.assertRaises(academic.AcademicAIResponseError):
                        guardrail.guarded_reply([], prompt, role=role)

    def test_retry_preserves_role(self):
        for role in ("PIA",):
            with patch("guardrail.reply", side_effect=["bad", '{"allowed":false,"violations":["role"]}', "good", '{"allowed":true,"violations":[]}']) as reply:
                self.assertEqual(guardrail.guarded_reply([], "Original", role=role), "good")
                retry = reply.call_args_list[2].args[1]
                self.assertIn("peer tutor" if role == "PIA" else "as the student", retry)


class StudyUITest(unittest.TestCase):
    def test_downloads_in_all_study_phases_include_enrolled_participant_id(self):
        snapshot = ready_snapshot()
        for phase in ("activity", "post_survey", "completed"):
            with self.subTest(phase=phase):
                state = flow.initial_study_state()
                state.update(phase=phase, group="B", participant_code="B-123")
                for activity_id in flow.GROUPS["B"]:
                    progress = flow.initial_activity_state()
                    progress.update(started=True, conversation_started=True, next_message=1,
                                    messages=[{"role": "user", "content": "Hallo", "timestamp": "2026-11-12T09:00:00+00:00"}])
                    state["activities"][activity_id] = progress
                token = session_store.SessionStore().create(snapshot, state)
                with patch("chat_export.chat_markdown", wraps=chat_markdown) as export:
                    app = self.resume(token)
                self.assertFalse(app.exception)
                self.assertEqual(export.call_count, 2 if phase == "completed" else 1)
                for call in export.call_args_list:
                    self.assertEqual(call.kwargs["participant_code"], "B-123")

    def setUp(self):
        completion = patch("completion.step_complete", return_value=True)
        completion.start()
        self.addCleanup(completion.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(session_store, "DB_PATH", Path(self.temp.name) / "sessions.sqlite3")
        patcher.start()
        self.addCleanup(patcher.stop)

    def resume(self, token):
        app = AppTest.from_file(APP, default_timeout=15)
        app.query_params["session"] = token
        app.run()
        self.assertFalse(app.exception)
        return app

    def test_default_study_is_blocked_without_showing_drafts(self):
        app = AppTest.from_file(APP).run()
        self.assertFalse(app.exception)
        self.assertTrue(app.button(key="welcome_next"))
        app.button(key="welcome_next").click().run()
        app.selectbox(key="study_group").select("A")
        app.text_input(key="participant_code").set_value("abc")
        app.button[0].click().run()
        self.assertTrue(app.error)
        self.assertFalse(app.chat_input)
        self.assertFalse(any("Entwurf" in text.value for text in app.markdown))

    def test_group_b_full_pia_activity_reaches_real_aila_script(self):
        snapshot = flow.load_study()
        self.assertEqual(flow.readiness_errors(snapshot, "B"), [])
        token = session_store.SessionStore().create(snapshot, flow.initial_study_state())
        app = self.resume(token)
        app.button(key="welcome_next").click().run()
        app.selectbox(key="study_group").select("B")
        app.text_input(key="participant_code").set_value("LOCAL-TEST-B")
        app.button[0].click().run()
        app.checkbox[0].check().run()
        app.button(key="survey_next").click().run()
        app.button(key="start_activity").click().run()
        self.assertFalse(app.exception)
        pia = registry.load_activity("pia_cables_and_tester")
        self.assertGreater(len(pia["tasks"]), 1)
        for index, task in enumerate(pia["tasks"]):
            if task.get("intro_sequence"):
                app.button(key="confirm_intro").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.main.subheader[-1].value, task["task_title"])
            self.assertEqual(app.get("progress")[0].proto.value, int(100 * index / len(pia["tasks"])))
            self.assertEqual(app.get("progress")[0].proto.text, f"Aufgabe {index + 1} von {len(pia['tasks'])}")
            self.assertFalse(any("Interne Anleitung für PIA" in m.value
                                 or "Erwartete Anordnung" in m.value
                                 for m in app.markdown))
            while (app.session_state["activity_state"]["action"] != "continue"
                   and not app.session_state["activity_state"]["answered"]):
                self.assertTrue(app.chat_input)
                with patch("guardrail.guarded_reply", return_value="Danke für deine Überlegung.") as reply:
                    step = app.session_state["activity_state"]["next_message"]
                    app.chat_input[0].set_value(f"Meine Überlegung zur Aufgabe {index}, Frage {step}.").run()
                    self.assertEqual(reply.call_args.kwargs["role"], "PIA")
                    self.assertIn("Stufe 1", reply.call_args.args[1])
                app.run()
            self.assertFalse(app.exception)
            if index < len(pia["tasks"]) - 1:
                app.button(key="next_task").click().run()
                app.button(key="confirm_next_task_yes").click().run()
        app.button(key="finish_activity").click().run()
        app.checkbox[0].check().run()
        app.button(key="survey_next").click().run()
        app.button(key="start_activity").click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.subheader[0].value, "Willkommen!")
        activity = registry.load_activity("aila_robot_and_batteries")
        first_message = activity["tasks"][0]["conversation"][0]["message"]
        self.assertTrue(any(m.value == first_message for m in app.markdown))
        self.assertFalse(any("Testabschnitt" in m.value for m in app.subheader))
        self.assertTrue(app.chat_input)
        restored = self.resume(token)
        self.assertTrue(any(m.value == first_message for m in restored.markdown))

    def test_both_group_walkthroughs_resume_and_context_isolation(self):
        for group in ("A", "B"):
            with self.subTest(group=group):
                snapshot = ready_snapshot()
                token = session_store.SessionStore().create(snapshot, flow.initial_study_state())
                app = self.resume(token)
                app.button(key="welcome_next").click().run()
                app.selectbox(key="study_group").select(group)
                app.text_input(key="participant_code").set_value(" Code ")
                app.button[0].click().run()
                self.assertFalse(app.exception)
                app = self.resume(token)
                for index in range(2):
                    self.assertTrue(app.button(key="survey_next").disabled)
                    app.checkbox[0].check().run()
                    app.button(key="survey_next").click().run()
                    app = self.resume(token)
                    app.button(key="start_activity").click().run()
                    self.assertFalse(app.exception)
                    activity_id = flow.GROUPS[group][index]
                    with patch("guardrail.guarded_reply", return_value="Antwort") as reply:
                        app.chat_input[0].set_value(f"Nachricht {index}").run()
                        self.assertFalse(app.exception)
                        self.assertEqual(reply.call_args.kwargs["role"], snapshot["activities"][activity_id]["role"])
                        self.assertEqual(reply.call_args.args[0], [{"role": "user", "content": f"Nachricht {index}"}])
                    app = self.resume(token)
                    app.button(key="finish_activity").click().run()
                    self.assertFalse(app.exception)
                    app = self.resume(token)
                    self.assertEqual(session_store.SessionStore().load(token)[1]["phase"], "post_survey")
                    self.assertEqual(len(app.get("download_button")), 1)
                app.checkbox[0].check().run()
                app.button(key="survey_next").click().run()
                app = self.resume(token)
                self.assertEqual(session_store.SessionStore().load(token)[1]["phase"], "completed")
                self.assertEqual(len(app.expander), 2)
                self.assertEqual(len(app.get("download_button")), 2)
                self.assertFalse(app.chat_input)
                self.assertFalse(app.button)


if __name__ == "__main__":
    unittest.main()
