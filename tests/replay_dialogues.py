"""Explicitly opt in to paid, nondeterministic end-to-end model replays."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dialogue_cases import CASES
from dialogue_runner import run_dialogue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List case IDs without model calls")
    parser.add_argument("--live", action="store_true", help="Call configured AcademicAI models")
    parser.add_argument("--case", action="append", choices=[c["id"] for c in CASES], help="Repeat to select multiple cases")
    parser.add_argument("--output", type=Path, help="JSON report (default data/dialogue-replays/<UTC>.json)")
    args = parser.parse_args()
    if args.list:
        print("\n".join(c["id"] for c in CASES))
        return 0
    if not args.live:
        parser.error("Use --list or explicitly opt in with --live.")
    output = args.output or Path(__file__).resolve().parents[1] / "data/dialogue-replays" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    report = {"mode": "live", "cases": []}
    selected = [c for c in CASES if not args.case or c["id"] in args.case]
    for case in selected:
        print(f"Running {case['id']} ...", flush=True)
        result = run_dialogue(case, live=True)
        report["cases"].append(result)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{case['id']}: {result['status']} {result.get('error', '')}", flush=True)
    print(f"Report: {output}", flush=True)
    return int(any(case["status"] != "passed" for case in report["cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
