"""Build PIA reply context without replaying old generated dialogue."""
import re


INTRODUCTION = re.compile(
    r"\b(?:ich\s+(?:bin|heiße|heisse)|mein\s+name\s+ist)\s+[^.!?;\n]{1,120}", re.I
)


def reply_context(activity, state, messages):
    """Keep the current exchange, prescribed background and accepted learning.

    No model summarizer is needed. Earlier model replies and whole learner
    messages are not copied into background, so old refusals stay out of it.
    """
    start = state.get("step_start", state["task_start"])
    current = [{"role": m["role"], "content": m["content"]} for m in messages[start:]]
    reference = []
    for index, task in enumerate(activity["tasks"][:state["task_index"] + 1]):
        entries = task.get("conversation", [])
        if index == state["task_index"]:
            entries = entries[:max(0, state["next_message"] - 1)]
        contents = [entry["message"] for entry in entries if entry.get("message")]
        if contents:
            reference.append({"task": task["task_title"], "content": contents})
    background = {"earlier_scripted_content": reference,
                  "accepted_learning": state.get("pia_completed_steps", [])}
    # Quote an introduction rather than guessing a name. "Ich bin bereit" is
    # just a self-description; it is never stored as an inferred participant name.
    first_user = next((m["content"] for m in messages[:start] if m["role"] == "user"), "")
    match = INTRODUCTION.search(first_user)
    if match:
        introduction = re.split(r"\s+(?:und|aber|kannst|lass|möchte)\b", match.group(), maxsplit=1, flags=re.I)[0]
        background["quoted_self_introduction"] = introduction
    return current, background


def remember_completed_step(state, task, step, assessment):
    """Remember assessed requirements, never raw off-topic learner requests."""
    criteria = assessment.get("criteria", [])
    if not criteria or not all(c["status"] == "met" for c in criteria):
        return
    memory = [entry for entry in state.get("pia_completed_steps", []) if entry["step"] != step]
    memory.append({"step": step, "task": task["task_title"],
                   "accepted_requirements": [c["requirement"] for c in criteria]})
    state["pia_completed_steps"] = memory
