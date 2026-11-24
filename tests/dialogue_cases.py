"""Dialogue expectations are test oracles, not copies of historic agent replies."""
import json
from pathlib import Path

CORPUS_PATH = Path(__file__).parent / "fixtures/dialogues/pilot_inputs.json"
CORPUS = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def pilot(source, section, turn):
    record = next(r for r in CORPUS if r["source"] == source)
    part = next(s for s in record["sections"] if s["title"] == section)
    return {"input": part["inputs"][turn], "source": source, "source_section": section, "source_turn": turn}


def pia(number, section, turn):
    return pilot(f"pia_cables_and_tester_chat_{number:02}.md", section, turn)


def aila(number, section, turn):
    return pilot(f"aila_robot_and_batteries_chat_{number:02}.md", section, turn)


def say(value, rubric=None, met=(), incorrect=(), **checks):
    entry = {"input": value, "source": "synthetic"} if isinstance(value, str) else value
    return {"action": "say", **entry, "rubric": rubric, "met": list(met), "incorrect": list(incorrect), **checks}


RUBRICS = {
    "ready": {"ready": "Die lernende Person ist bereit anzufangen."},
    "plan": {"plan": "Ein gültiger Plan identifiziert das defekte von zwei Kabeln."},
    "problem": {
        "resources": "Zwei Kabel, zwei Tester und genau ein defektes Kabel sind gegeben.",
        "unknown": "Unbekannt ist, welches Kabel defekt ist.",
        "goal": "Ziel ist die Identifikation des defekten Kabels.",
        "capacity": "An einem Tester dürfen bis zu zwei Kabel angeschlossen werden.",
        "round": "Der Testplan steht vor einer einzigen Testrunde unveränderlich fest.",
        "results": "ON bedeutet alle angeschlossenen Kabel funktionieren, OFF mindestens eines ist defekt.",
    },
    "decomposition": {
        "resources": "Die Ressourcen sind zwei Kabel und zwei Tester.",
        "fault": "Genau ein Kabel ist defekt.",
        "capacity": "Maximal zwei Kabel können an einen Tester angeschlossen werden.",
        "round": "Eine Testrunde mit unveränderlichem vorher festgelegtem Plan ist erlaubt.",
        "results": "ON: alle angeschlossenen Kabel funktionieren; OFF: mindestens eines ist defekt.",
    },
    "off": {"off": "Bei OFF und einem angeschlossenen Kabel ist dieses Kabel defekt.",
            "reason": "Weil nur ein Kabel angeschlossen ist, kann OFF nur dieses Kabel betreffen."},
    "combinations": {"four": "Alle vier Kombinationen ON/ON, ON/OFF, OFF/ON und OFF/OFF sind aufgelistet."},
    "mapping": {"unique": "Jedes mögliche defekte Kabel erzeugt ein anderes Ergebnispaar."},
    "sorting": {"order": "Aufsteigend bedeutet von klein nach groß.",
                "invariant": "Vertauschen verändert Positionen, nicht Werte oder Häufigkeiten."},
    "explanation": {"reason": "Die Erklärung begründet, warum das Ergebnis gilt."},
}

ALL_PROBLEM = tuple(RUBRICS["problem"])
ALL_DECOMP = tuple(RUBRICS["decomposition"])
PIA = "pia_cables_and_tester"
AILA = "aila_robot_and_batteries"

CASES = [
    {"id": "pia_readiness", "activity": PIA, "start_task": 0, "actions": [
        say(pia(1, "Willkommen", 0), "ready", ("ready",), off_topic=True),
        say(pia(1, "Willkommen", 1), "ready", ("ready",), off_topic=True),
        {"action": "next", "task_index": 1},
    ]},
    {"id": "pia_plan_and_problem", "activity": PIA, "start_task": 1, "actions": [
        say(pia(1, "Einführung in das Szenario", 0), "plan"),
        say(pia(1, "Einführung in das Szenario", 1), "plan"),
        say(pia(1, "Einführung in das Szenario", 2), "plan", ("plan",), next_message=9),
        {"action": "next", "task_index": 2},
        say(pia(2, "Problemformulierung", 0), "problem", ("resources", "unknown", "goal")),
        say(pia(2, "Problemformulierung", 1), "problem", ("resources", "unknown", "goal")),
        say("Maximal zwei Kabel je Tester; ein unveränderlicher Plan für eine Testrunde. ON: alle angeschlossenen funktionieren; OFF: mindestens eines ist defekt.", "problem", ALL_PROBLEM),
        {"action": "resume"},
    ]},
    {"id": "pia_partial_decomposition", "activity": PIA, "start_task": 3, "actions": [
        say(pia(3, "Dekomposition", 0), "decomposition", ("resources",)),
        {"action": "resume"},
        say(pia(3, "Dekomposition", 1), "decomposition", ("resources",)),
        say(pia(3, "Dekomposition", 2), "decomposition", ("resources", "fault"), ("round",)),
        say(pia(3, "Dekomposition", 3), "decomposition", ("resources", "fault"), ("round",)),
        say(pia(3, "Dekomposition", 4), "decomposition", ("resources", "fault", "results"), ("round",)),
        say("Es dürfen maximal zwei Kabel an jeden Tester. Wir haben eine einzige Testrunde; der Plan steht vorher fest und bleibt unverändert.", "decomposition", ALL_DECOMP),
    ]},
    {"id": "pia_patterns", "activity": PIA, "start_task": 4, "actions": [
        say(pia(4, "Muster erkennen", 0), "off", ("off",), navigation=False),
        say("Es ist nur dieses eine Kabel angeschlossen. Deshalb kann die OFF-Anzeige nur bedeuten, dass genau dieses Kabel defekt ist.", "off", ("off", "reason"), next_message=2, navigation=False),
        say(pia(4, "Muster erkennen", 1), "combinations", ("four",), next_message=3, navigation=False),
        say("Der feste Testplan ordnet jedem möglichen defekten Kabel ein anderes Ergebnispaar zu. Deshalb identifiziert das beobachtete Paar genau ein Kabel.", "mapping", ("unique",), next_message=4),
    ]},
    {"id": "pia_correction_and_contradiction", "activity": PIA, "start_task": 3, "actions": [
        say("Zwei Kabel und zwei Tester, eines defekt. Es gibt eine Testrunde mit festem unveränderlichem Plan.", "decomposition", ("resources", "fault", "round")),
        say("Es sind doch zwei Runden und höchstens ein Kabel pro Tester.", "decomposition", ("resources", "fault"), ("round", "capacity")),
        say("Korrektur: eine Testrunde mit vorher festem Plan, maximal zwei Kabel je Tester.", "decomposition", ("resources", "fault", "round", "capacity")),
        say("habe ich doch schon?!", "decomposition", ("resources", "fault", "round", "capacity")),
        say("ON: alle angeschlossenen Kabel funktionieren. OFF: mindestens eines ist defekt.", "decomposition", ALL_DECOMP),
    ]},
    {"id": "pia_sorting", "activity": "synthetic_sorting", "start_task": 0, "actions": [
        say("Aufsteigend heißt von klein nach groß.", "sorting", ("order",)),
        {"action": "resume"},
        say("Nur die Positionen ändern sich. Werte und ihre Häufigkeiten bleiben erhalten.", "sorting", ("order", "invariant")),
        {"action": "next", "task_index": 1},
        say("weiter", "explanation"),
        say("Das Ergebnis gilt, weil beim Vertauschen kein Wert hinzugefügt oder entfernt wird.", "explanation", ("reason",)),
        {"action": "finish"},
    ]},
    {"id": "pia_validator_retry", "activity": PIA, "start_task": 0, "actions": [
        say("Ich bin bereit.", "ready", ("ready",), bad_draft="Hallo Alex! Ich bleibe bei unserer Aufgabe."),
        {"action": "next", "task_index": 1},
    ]},
    {"id": "aila_confirmations", "activity": AILA, "start_task": 1, "actions": [
        say(aila(1, "Problemformulierung", 2)),
        say(aila(1, "Problemformulierung", 3), exact="Danke!"),
        say(aila(1, "Problemformulierung", 4)),
        say(aila(1, "Problemformulierung", 5), exact="Danke!"),
        say(aila(1, "Problemformulierung", 6), exact="Danke!"),
    ]},
    {"id": "aila_praise_and_navigation", "activity": AILA, "start_task": 4, "actions": [
        say(aila(2, "Muster erkennen", 0)),
        say(aila(2, "Muster erkennen", 1), exact="Danke!"),
        say(aila(2, "Muster erkennen", 2), exact="Danke!"),
        {"action": "next", "task_index": 5},
        say(aila(2, "Verbindungslinien-Formel", 0), no_solution=True),
        say(aila(2, "Verbindungslinien-Formel", 1), no_solution=True),
    ]},
]


def load_case_activity(case):
    from content_registry import load_activity
    if case["activity"] != "synthetic_sorting":
        return load_activity(case["activity"])
    # This fixture lives outside learning_activities and never changes an activity.
    return {"activity_id": PIA, "role": "PIA", "activity_name": "Synthetic sorting",
            "intro_sequence": "intro.md", "tasks": [
                {"task_title": "Ascending order", "conversation": [{
                    "message": "Definiere aufsteigende Reihenfolge und erkläre, warum Vertauschen die Werte erhält.",
                    "system_info": "Erwartet: klein nach groß; Werte und Häufigkeiten ändern sich nicht. Kein Sortieralgorithmus verlangt.",
                }]},
                {"task_title": "Justification", "conversation": [{
                    "message": "Warum bleiben die Werte beim Vertauschen erhalten?",
                    "system_info": "Vertauschen ändert nur Positionen, fügt keine Werte hinzu und entfernt keine.",
                }]},
            ]}
