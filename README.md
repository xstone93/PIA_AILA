# PIA / AILA computational thinking study

One Streamlit app supports PIA (peer tutor) and AILA (student taught by the participant).

| Group | First activity | Second activity |
|---|---|---|
| A | PIA Robot & Batteries | AILA Cables & Tester |
| B | PIA Cables & Tester | AILA Robot & Batteries |

Welcome → enrollment → pre-study questionnaire → first activity → questionnaire → second activity → questionnaire → completion.

## Run and test

From the repository root with Python 3.11 or later:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
python -m unittest discover -s tests -v
```

Model requests require `ACADEMIC_AI_CLIENT_ID` and `ACADEMIC_AI_CLIENT_SECRET` in `.streamlit/secrets.toml`. Tests mock model calls and use temporary databases.

### Test an individual activity or chat

Open `http://localhost:8501/?preview=1` (use your running server's port). Choose an activity and either **Gesamte Aktivität** or a numbered section, then click **Chat starten**. Individual sections start with fresh chat history and retain their information pages; they skip enrollment, questionnaires and earlier sections. Only complete, validated activities are offered. Replies use the normal model and guardrails.

Use **Andere Aufgabe auswählen** to start another fresh preview with the latest content and role rules. Save the complete `?preview=1&session=...` URL to resume. Preview sessions use `data/preview_sessions.sqlite3`, separately from study records. The normal URL continues to start the study flow.

## Prepare the study

**The study is not ready for real participants.** Group B contains the full PIA Cables & Tester activity followed by the AILA Robot & Batteries script. Group A still contains draft activities. Survey links currently point to example.org as local test placeholders.

PIA Cables & Tester is based on `PIA Cables.docx`: its JSON contains all teaching context, diagrams, learner questions and private answer guidance. Only the glossary from `cables_and_tester_03.md` appears in the sidebar, available throughout the activity via **Information**. The activity retains only that glossary and the launch page `intro.md`; the unused numbered Markdown files have been removed. Older sessions referencing removed introduction pages require a fresh session. PIA acts as tutor and the participant as learner. Each question allows follow-up discussion, with the three-level hint protocol reset for each subtask.

To test Group B, run `python -m streamlit run app.py` and open its URL without
`?session=...` (do not use the old preview on port 8517). Select B and enter any
test participant code. Confirm the first questionnaire, complete the PIA activity,
and confirm the next questionnaire. Click
**Weiter** on the AILA introduction to start its real scripted conversation.
The placeholder questionnaires can be confirmed directly during local testing.
AILA replies require the configured AcademicAI credentials.

1. Review `study/welcome.md`, `study/questionnaire.md`, and `study/completion.md` with the study team.
2. Edit `study/config.json`: set the study `version`, `pre_study`, and `post_activity` checkpoints. There is one post-activity checkpoint per activity identifier. Each needs an HTTP(S) `survey_url`. The `markdown` filename is optional (omit it or use `null` for a link-only checkpoint). Files are relative to `study/`. Links and text may be reused.
3. Complete the two remaining draft activity definitions. Fill `tasks`, review tutor/learner behavior for all activities, and set completed drafts to `ready`.
4. Run `python -m study_flow` for preflight. Exit code 1 means configuration needs attention; exit code 0 means both groups are configured. This does not write to the database.
5. Open a **new session without `?session=`** to test changed configuration. Walk through both groups and all three survey checkpoints.

Survey buttons open a separate tab. Participants return and confirm completion explicitly. Records include a UTC timestamp and `verification: self_reported`; the app does not verify LimeSurvey responses. No participant code or session token is appended to survey URLs.

## Content structure

```text
learning_activities/
  pia/
    role.md
    robot_and_batteries/robot-and-battery_pia.json
    cables_and_tester/cables-and-tester_pia.json
  aila/
    role.md
    robot_and_batteries/robot-and-battery_aila.json
    cables_and_tester/cables-and-tester_aila.json
study/
  config.json
  welcome.md
  questionnaire.md
  completion.md
```

Each activity folder owns its Markdown and figures. AILA robot preparation and teaching directions live in Markdown; flexible section guidance lives in the activity JSON. The tutor controls the conversation and section navigation.

`activity_id` is stable, for example `aila_robot_and_batteries`. `role` is `PIA` or `AILA`, `activity_name` is the display title, and `status` is `draft` or `ready`. Activity `intro_sequence` names one Markdown file. The JSON `tasks` array holds internal sections with `task_title`, an optional list of Markdown `intro_sequence` pages, and `conversation` entries.

Reusable instructions live in each role's `role.md`. Optional activity `role_description` and `system_info` supplement them. AILA receives role and section guidance in one generation request; its replies are not classified, rewritten or blocked by a second model. PIA retains response validation and learner-answer completion checking. Role adherence is model-based guidance, not a guarantee. AcademicAI instructions are embedded in a copy of the latest user turn because the adapter accepts user/assistant roles.

## Activity behavior

- **Chat herunterladen** exports the current visible transcript as UTF-8 Markdown with activity name, role, study participant ID (`participant_code`), UTC export date, task headings and speaker labels. Each message includes its timestamp, displayed in Europe/Vienna time (CET/CEST), matching the chat. Available during activities, at post-activity questionnaires, and for each transcript at study completion. Diagrams become text references. Internal instructions, unrevealed scripted messages and session links remain excluded. Previews without enrollment show “Nicht hinterlegt” for the participant ID. Anything participants type in chat remains part of their transcript.
- New user, generated-agent and visible scripted-agent messages store a UTC `timestamp` once when created. User time is captured on submission; generated-agent time is captured after the response is available. Reloads and exports reuse those stored times. Older messages without timestamps show “Zeitstempel nicht verfügbar”; their dates are not fabricated. Message timestamps are display/persistence metadata and are not added to model requests. No database migration is needed.
- A compact progress bar above the chat controls shows the current section for both PIA and AILA. It counts sections already passed and reaches 100% when the activity is finished; individual chat messages do not count as separate tasks.
- `message` is Markdown; `type: "bold"` emphasizes it and `type: "image"` displays a local image. Paths are relative to the activity JSON.
- Omit `message` to wait silently for the participant. No request occurs before the user sends a message.
- `action: "no_wait"` reveals the next entry immediately; default `wait` waits for input; `continue` offers navigation without another exchange.
- PIA validates the response, then separately assesses the learner's answer before advancing a scripted question or unlocking navigation. Unusable completion decisions preserve the exchange and show a warning. AILA makes one generation request, saves the exchange and leaves section completion to the human tutor. After a successful exchange the tutor may keep chatting or explicitly confirm navigation; no model grades the tutor or gates explanation/application phases. API failures do not save the failed exchange or advance progress.
- PIA Cables & Tester groups each topic into one task with multiple `conversation` entries. For example, all four entries for **Muster erkennen** share one heading; the next-topic button appears after the topic's final entry.
- Section intros appear in the information sidebar. Markdown images and `<details><summary>…</summary>…</details>` expanders are supported. `![Alt](figures/image.png){width=240}` sets optional image width.
- An activity may set `sidebar_reference` to a Markdown reference page available throughout the chat. This does not pause the conversation or require an introduction confirmation. PIA Cables & Tester uses this for its glossary and keeps teaching context in chat messages.
- Internal sections share one activity conversation. The second study activity gets a fresh model context. Both transcripts remain saved and can be reviewed at study completion.
- Finishing each activity leads to its questionnaire. Only the final questionnaire confirmation completes the study.

## Persistence and compatibility

Sessions live in `data/sessions.sqlite3`. Keep it on persistent storage and back it up before deployment. An additive migration creates nullable `study_group`, `participant_code`, and `study_version` columns without removing existing records. Enrollment is locked after submission. Codes are trimmed, case-preserving, and may occur in multiple sessions.

Save the random `?session=...` link to resume on any device reaching the same server. Anyone with this link can access the session; there is no account login or lookup by code. Stale saves from another tab are rejected. Unsent input and interrupted requests are not saved.

Sessions snapshot study configuration, study Markdown text, role instructions, and activity JSON at creation. Configuration changes require a new session, including sessions created while configuration was incomplete. Activity Markdown and images remain file-backed; retain their paths for ongoing sessions. Existing sessions continue as standalone AILA activities with relocated content and no retroactive enrollment. API credentials are never stored in the database.

## Code organization

`content_registry.py` resolves and validates activities; `study_flow.py` owns study transitions; `study_ui.py` renders study pages. `app.py` coordinates these with shared activity UI. `activity.py` handles sections, prompts and progression; `guardrail.py` sends AILA replies directly and validates PIA replies; `completion.py` checks PIA learner answers; `academic.py` sends model requests; `session_store.py` manages SQLite. `presentation.py` and `timing.py` provide styling and timing diagnostics.

Console timing records requests and saves without logging prompts, replies, participant codes, credentials, or session links.

AILA normally makes **one model request** per message. PIA normally makes three (generation, validation and completion), with at most one generation/validation retry. There is no transition classifier, AILA completion classifier, evidence heuristic or quality-repair fallback. Technical HTTP, JSON and nonempty-response checks remain in `academic.py` for every API request.

For PIA errors, `guardrail_error` includes a reason and reference. `completion_error` identifies a technical learner-answer check failure; this preserves the exchange without unlocking navigation. A valid `step_complete=false` is an ordinary unfinished PIA step. Normal console logs exclude drafts and model-generated reasons.

### Inspecting model decisions locally

Detailed diagnostics are **off by default**. Enable them explicitly in the terminal used to launch Streamlit:

```powershell
$env:AILA_DIAGNOSTICS = '1'
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Reproduce the issue and look up the displayed reference in `data/model_diagnostics.jsonl`:

```powershell
Get-Content data/model_diagnostics.jsonl -Encoding utf8 |
    ConvertFrom-Json | Where-Object reference -EQ 'REFERENCE_FROM_ERROR' |
    ConvertTo-Json -Depth 20
```

AILA records `response_generated` with its section and reply. There are no AILA rejection or completion classifications. PIA records validator reasons, retries and completion explanations. Records contain participant text and internal model content: they stay in the git-ignored `data/` directory, are excluded from the learner UI and chat export, and are not automatically deleted. No credentials or session identifiers are added by the recorder. Delete diagnostic files when no longer needed. Disable collection with `Remove-Item Env:AILA_DIAGNOSTICS`, then restart Streamlit.

New AILA robot sessions use one conversation entry per section with flexible teaching guidance. Sections and left-panel materials are unchanged. Saved sessions retain their original snapshot; legacy silent explanation/application entries are made available together in the prompt and no longer gate navigation. No stored sessions are migrated or rewritten. For a clean comparison with the new content, start a **new preview session**.
