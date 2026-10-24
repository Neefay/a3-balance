"""Validate the balance pilot's in-game verification parts from one RPT.

Usage: python import_balance_verification.py <rpt> <output.json> [--pilot balance-pilot] [--run PART=RUN ...]
"""
import argparse
import json
from pathlib import Path

from import_clean_capture import read_records


def validate_part(records, manifest, part):
    build_id, expected = manifest["build_id"], manifest["parts"][part - 1]
    if len(records) < 2 or records[0][:5] != ["BEGIN_PILOT", 2, build_id, part, len(manifest["parts"])] or records[-1][:4] != ["END_PILOT", 2, build_id, part]:
        raise ValueError(f"Part {part}: missing/mismatched verification boundaries or build ID")
    end = records[-1]
    if len(end) != 9 or end[4] != len(records) or end[5:7] != [expected["classes"], expected["fields"]] or records[0][5] != expected["classes"]:
        raise ValueError(f"Part {part}: did not check the complete expected class/field set")
    failures = records[1:-1]
    if any(record[0] != "FAILURE" for record in failures) or len(failures) != end[8] or end[7] < len(failures):
        raise ValueError(f"Part {part}: failure records disagree with the summary")
    return {"part": part, "passed": end[7] == 0, "checked_classes": end[5], "checked_fields": end[6],
            "failure_count": end[7], "reported_failures": failures, "product_version": records[0][6], "loaded_mods": records[0][7]}


def validate(rpt, manifest, runs=None):
    results = []
    for entry in manifest["parts"]:
        part = entry["part"]
        run, records = read_records(rpt, (runs or {}).get(part), f"A3BALP{part}".encode())
        results.append({"run": run, **validate_part(records, manifest, part)})
    return {"build_id": manifest["build_id"], "passed": all(result["passed"] for result in results),
            "checked_classes": sum(result["checked_classes"] for result in results),
            "checked_fields": sum(result["checked_fields"] for result in results),
            "failure_count": sum(result["failure_count"] for result in results), "parts": results,
            "limits": "Effective config/ancestry checks only; damage behavior, geometry and shots-to-kill are not measured."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("rpt", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--pilot", default="balance-pilot", help="pilot build folder (default: balance-pilot)")
    parser.add_argument("--run", action="append", default=[], help="PART=RUN when a part was run more than once")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / args.pilot / "manifest.json").read_text())
    runs = {int(part): run for part, run in (item.split("=", 1) for item in args.run)}
    result = validate(args.rpt, manifest, runs)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
    print(json.dumps({key: result[key] for key in ("passed", "checked_classes", "checked_fields", "failure_count")}))
    if not result["passed"]:
        raise SystemExit(1)
