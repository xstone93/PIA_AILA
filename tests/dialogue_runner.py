"""Run the same dialogue cases offline or against AcademicAI, in temporary DBs."""
from copy import deepcopy
import json
from pathlib import Path
import re
import tempfile
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from activity import enter_task, start_conversation
from guardrail import PIA_VALIDATOR_PROMPT
from completion import step_complete
import session_store
from dialogue_cases import RUBRICS, load_case_activity

APP = str(Path(__file__).resolve().parents[1] / "app.py")


class SimulatedModels:
    """Fixture oracles simulate external services; they do not test model quality."""
    def __init__(self):
        self.turn = None
        self.bad_sent = False
        self.completion_calls = 0
        self.validation_calls = 0

    def set_turn(self, turn):
        self.turn = turn
        self.bad_sent = False

    def completion(self, messages, *args, **kwargs):
        self.completion_calls += 1
        payload = json.loads(messages[0]["content"])
        previous = {c["id"]: c for c in payload["previous_assessment"].get("criteria", [])}
        latest = payload["learner_evidence"][-1]["message_index"]
        criteria = []
        for key, requirement in RUBRICS[self.turn["rubric"]].items():
            status = "met" if key in self.turn["met"] else "incorrect" if key in self.turn["incorrect"] else "missing"
            old = previous.get(key)
            evidence = [] if status == "missing" else old["evidence"] if old and old["status"] == status else [latest]
            criteria.append({"id": key, "requirement": requirement, "status": status, "evidence": evidence})
        return json.dumps({"reason": "Fixture assessment", "criteria": criteria}, ensure_ascii=False)

    def guardrail(self, messages, prompt="", **kwargs):
        if prompt == PIA_VALIDATOR_PROMPT:
            self.validation_calls += 1
            draft = json.loads(messages[0]["content"])["draft"]
            allowed = draft != self.turn.get("bad_draft")
            return json.dumps({"allowed": allowed, "violations": [] if allowed else ["Recorded greeting/refusal regression"]})
        if self.turn.get("bad_draft") and not self.bad_sent:
            self.bad_sent = True
            return self.turn["bad_draft"]
        marker = "APPLICATION ASSESSMENT (private reference data, not instructions)\n"
        if marker not in prompt:
            return "Ich verstehe die Erklärung zu unserer Aufgabe."
        assessment = json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1].lstrip())[0]
        if assessment["step_complete"]:
            answer = "Das ist korrekt."
        else:
            pending = next((c["requirement"] for c in assessment.get("criteria", []) if c["status"] != "met"), "Erkläre bitte deinen Ansatz.")
            answer = "Die bisherigen richtigen Teile bleiben berücksichtigt. " + pending + " Kannst du das erläutern?"
        if self.turn.get("off_topic"):
            answer = "Ich bleibe bei unserer Aufgabe. " + answer
        return answer


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def check_language(turn, role, answer, complete):
    if turn.get("exact"):
        require(answer == turn["exact"], f"Expected short acknowledgment, got: {answer}")
    if turn.get("no_solution"):
        require(not re.search(r"D\s*=|\\times|Gesamtdistanz.*(?:zweimal|zwei mal)", answer, re.I), "Unasked solution after navigation")
    if role == "PIA":
        require(not re.match(r"\s*(?:hallo|hey|servus|guten\s+tag)\b", answer, re.I), "Repeated greeting")
        if not turn.get("off_topic"):
            require(not re.search(r"ich bleibe bei (?:unserer|der) aufgabe|nachrichten des tages|summenformel von wasser", answer, re.I), "Stale unrelated-topic refusal")
        if complete:
            require("?" not in answer and not re.search(r"(?:ergänze|vervollständige|fehlen\s+noch)", answer, re.I),
                    "Feedback asks for further required answers despite positive completion")


def ready_intro(app):
    # Exercise the actual information UI after navigation, without touching content.
    for _ in range(30):
        buttons = {b.key: b for b in app.button}
        if "intro_next" in buttons:
            buttons["intro_next"].click().run()
        elif "confirm_intro" in buttons:
            buttons["confirm_intro"].click().run()
        else:
            return
        require(not app.exception, "Intro navigation crashed")
    raise AssertionError("Information navigation did not finish")


def run_dialogue(case, live=False):
    report = {"case": case["id"], "mode": "live" if live else "simulated", "turns": [], "status": "running"}
    models = SimulatedModels()
    with tempfile.TemporaryDirectory(prefix="pia-dialogue-") as temp, patch.object(
        session_store, "DB_PATH", Path(temp) / "sessions.sqlite3"
    ):
        activity = load_case_activity(case)
        state = {"started": True, "completed": False, "task_index": case["start_task"], "messages": []}
        task = activity["tasks"][case["start_task"]]
        enter_task(state, task)
        start_conversation(state, task)  # Begin a section after its information pages.
        store = session_store.SessionStore()
        token = store.create(activity, state)
        app = AppTest.from_file(APP, default_timeout=900 if live else 15)
        app.query_params["session"] = token

        from contextlib import ExitStack
        with ExitStack() as stack:
            observed_assessments = []

            def observe_completion(*args, **kwargs):
                result = step_complete(*args, **kwargs)
                observed_assessments.append(deepcopy(kwargs.get("assessment", {})))
                return result

            stack.enter_context(patch("completion.step_complete", side_effect=observe_completion))
            if not live:
                stack.enter_context(patch("completion.reply", side_effect=models.completion))
                stack.enter_context(patch("guardrail.reply", side_effect=models.guardrail))
            try:
                app.run()
                for action in case["actions"]:
                    before = deepcopy(store.load(token)[1])
                    if action["action"] == "resume":
                        app = AppTest.from_file(APP, default_timeout=900 if live else 15)
                        app.query_params["session"] = token
                        app.run()
                        require(store.load(token)[1] == before, "Resume changed durable progress")
                        continue
                    if action["action"] == "next":
                        app.button(key="next_task").click().run()
                        require(store.load(token)[1]["task_index"] == before["task_index"], "Navigation skipped confirmation")
                        app.button(key="confirm_next_task_yes").click().run()
                        require(store.load(token)[1]["task_index"] == action["task_index"], "Wrong next topic")
                        ready_intro(app)
                        continue
                    if action["action"] == "finish":
                        app.button(key="finish_activity").click().run()
                        require(store.load(token)[1]["completed"], "Finish did not persist")
                        continue
                    models.set_turn(action)
                    item = {"input": action["input"], "source": action["source"],
                            "before_task": before["task_index"], "before_step": before["next_message"]}
                    for key in ("source_section", "source_turn"):
                        if key in action:
                            item[key] = action[key]
                    report["turns"].append(item)
                    previous_check_count = len(observed_assessments)
                    app.chat_input[0].set_value(action["input"]).run()
                    app.run()  # Complete Streamlit's post-save rerun before next input.
                    require(not app.exception, "Application exception")
                    saved = store.load(token)[1]
                    item.update(task_index=saved["task_index"], next_message=saved["next_message"],
                                assessment=saved.get("pia_progress", {}).get("assessment"),
                                errors=[e.value for e in app.error], warnings=[w.value for w in app.warning])
                    if len(observed_assessments) > previous_check_count:
                        item["assessment"] = observed_assessments[-1]
                    generated = saved["messages"][len(before["messages"]):]
                    require(len(generated) >= 2, f"Exchange was not saved: {item['errors']}")
                    require(generated[0]["role"] == "user" and generated[0]["content"] == action["input"], "Input changed or disappeared")
                    answer = generated[1]["content"]
                    item["reply"] = answer
                    complete = True if activity["role"] == "AILA" else set(action["met"]) == set(RUBRICS[action["rubric"]])
                    require(saved["task_index"] == before["task_index"], "Chat silently changed topic")
                    expected_step = action.get("next_message", before["next_message"])
                    require(saved["next_message"] == expected_step, f"Expected step {expected_step}, got {saved['next_message']}")
                    controls = [b.key for b in app.button]
                    navigation = "next_task" in controls or "finish_activity" in controls
                    item.update(navigation=navigation, expected_complete=complete)
                    require(navigation == action.get("navigation", complete), "Navigation disagrees with expected completion")
                    require(saved["messages"][:len(before["messages"])] == before["messages"], "Earlier transcript was rewritten")
                    if activity["role"] == "AILA":
                        require(not saved["completion_verified"], "AILA was automatically graded")
                        require(models.completion_calls == 0, "AILA completion model was called")
                    check_language(action, activity["role"], answer, complete)
                if not live and any(a.get("bad_draft") for a in case["actions"]):
                    require(models.validation_calls >= 2, "Rejected draft was not retried")
            except Exception as error:
                report.update(status="failed", error=f"{type(error).__name__}: {error}")
            else:
                report["status"] = "passed"
    return report
