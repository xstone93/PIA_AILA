# Pilot dialogue regression cases

`pilot_inputs.json` contains learner inputs from the six supplied pilot protocols:
four PIA cable/tester protocols and two AILA robot/battery protocols. Names were
replaced with Alex. Participant IDs, timestamps, session links, and historic agent
answers are not included. Source basenames, section titles, and zero-based turn
numbers identify each input. Overlapping protocols intentionally remain traceable.
Original files are not required when running the tests.

The curated cases in `tests/dialogue_cases.py` combine selected original inputs
with marked synthetic additions. They are regression scenarios, not verbatim
reproductions of the old conversations. In particular, an old incorrect agent
acceptance is not treated as a correct expected outcome. The full extracted input
corpus remains available for adding further cases.

## Offline tests

```powershell
python -m unittest discover -s tests -p test_dialogue_replays.py -v
```

The runner uses Streamlit AppTest, the real activity/progression/persistence code,
and temporary SQLite databases. External assessment, generation and validation
responses are simulated using explicit test expectations. It checks each round:
stored inputs, progression, navigation controls, unchanged earlier history,
reopening a session, and expected short acknowledgments. An injected bad draft
exercises the real validation/retry loop. No API requests or production session
writes occur. These tests verify orchestration; they do not demonstrate real
model quality.

## Live model replays

```powershell
python tests/replay_dialogues.py --list
python tests/replay_dialogues.py --live --case pia_readiness
python tests/replay_dialogues.py --live --case pia_partial_decomposition --case pia_patterns
```

`--live` explicitly enables requests to the configured AcademicAI generation,
assessment and validation models using the existing Streamlit secrets. It may
incur costs and take several minutes. With no `--case`, all curated cases run.
Normal unittest discovery never enables this mode.

Each scenario feeds its predefined learner inputs into the actual app; agent
answers and decisions come from the real model, not the original transcript.
User navigation follows the expected controls. A failure stops that scenario
instead of silently skipping a blocked step. Other selected scenarios continue.
Reports default to `data/dialogue-replays/<UTC>.json`; `--output` overrides the
path. Reports contain anonymized inputs, generated replies, decisions, UI state,
and failure reasons, but no credentials or session links. Sessions remain in
temporary databases. Activity files are read without modification.

Live checks include expected progression, no repeated PIA greeting, no familiar
stale refusal, no extra completion question after positive completion, and no
AILA solution after plain navigation. Text checks are targeted heuristics, not
semantic proofs. Inspect the recorded replies as well as pass/fail status.
There is deliberately no second model judge that could simply repeat the same
model's mistakes. Known grading/feedback inconsistencies remain visible as
failures; test expectations must not be loosened to hide them.

## Covered scenarios

- `pia_readiness`: mixed readiness/off-topic requests and next-topic confirmation.
- `pia_plan_and_problem`: skipping, clarification, a valid two-tester plan,
  a new task requiring its own answer, and accumulated answers.
- `pia_partial_decomposition`: partial and wrong answers, a missing-button report,
  correction of remaining requirements, and resume.
- `pia_patterns`: automatic movement between questions within a topic, multiline
  combinations, and topic navigation only at the end. The original first answer
  identifies the faulty cable; a synthetic next turn supplies the explanation
  explicitly required by the unchanged activity's answer reference.
- `pia_correction_and_contradiction`: accepted facts, later contradiction,
  correction, and feedback that an answer was already supplied.
- `pia_sorting`: another task type, accumulated answers, resume, navigation alone
  not solving a new question, and finishing.
- `pia_validator_retry`: an injected repeated greeting/stale refusal is rejected
  in the simulated validator and the app retries generation.
- `aila_confirmations`: questions followed by brief confirmations; no automatic
  grading or required question coverage.
- `aila_praise_and_navigation`: praise and repeated "weiter" do not reveal an
  unasked formula or change topic without user-controlled navigation.

AILA behavior and all `learning_activities` files are unchanged. The AILA cases
exercise existing behavior only. Feedback points 8 and 9 are outside these tests.
