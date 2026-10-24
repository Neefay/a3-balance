"""Validate the helmet pilot's bounded effective-config verification summary."""
import argparse
import json
from pathlib import Path

from import_clean_capture import read_records


def validate_pilot(records, manifest):
    build_id = manifest["build_id"]
    if len(records) < 2 or records[0][:3] != ["BEGIN_PILOT", 1, build_id] or records[-1][:3] != ["END_PILOT", 1, build_id]:
        raise ValueError("Missing/mismatched pilot verification boundaries or build ID")
    end = records[-1]
    expected_classes = manifest["materialized_iteminfo_classes"]
    expected_fields = manifest["verified_fields_expected"]
    if len(end) != 8 or end[3] != len(records) or end[4:6] != [expected_classes, expected_fields] or records[0][3] != expected_classes:
        raise ValueError("Pilot verification did not check the complete expected class/field set")
    failures = records[1:-1]
    if any(record[0] != "FAILURE" for record in failures) or len(failures) != end[7] or end[6] < len(failures):
        raise ValueError("Pilot failure records disagree with the summary")
    return {"build_id": build_id, "passed": end[6] == 0 and not failures,
            "checked_classes": end[4], "checked_fields": end[5], "failure_count": end[6],
            "reported_failures": failures, "product_version": records[0][4], "loaded_mods": records[0][5],
            "limits": "Effective config/ancestry checks only; damage behavior, geometry and shots-to-kill are not measured."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("rpt", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--run")
    parser.add_argument("--pilot", default="helmet-pilot", help="pilot build folder (default: helmet-pilot)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / args.pilot / "manifest.json").read_text())
    run, records = read_records(args.rpt, args.run, b"A3BALPILOT")
    result = {"run": run, **validate_pilot(records, manifest)}
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
    print(json.dumps({key: result[key] for key in ("run", "passed", "checked_classes", "checked_fields", "failure_count")}))
    if not result["passed"]:
        raise SystemExit(1)
