"""Import range-test frames into a NEW directory: per-trial CSV, aggregate CSV and a summary."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import statistics

from import_clean_capture import read_records


def validate(records, manifest):
    """Infantry RESULT and vehicle VEHICLE_RESULT records between matching BEGIN/END frames."""
    suite, version = manifest["suite_id"], manifest.get("version", 1)
    if len(records) < 2 or records[0][:3] != ["BEGIN_RANGE", version, suite] or records[-1][:3] != ["END_RANGE", version, suite]:
        raise ValueError("Missing/mismatched range-test boundaries or suite ID")
    begin, end = records[0], records[-1]
    results = records[1:-1]
    if end[3] != len(records) or end[4] != len(results) or any(r[0] not in ("RESULT", "VEHICLE_RESULT") for r in results):
        raise ValueError("Range-test records disagree with the END summary")
    missing = begin[11]
    infantry = sum(r[0] == "RESULT" for r in results)
    vehicles = len(results) - infantry
    if not missing and infantry != manifest["expected_results"]:
        raise ValueError(f"Expected {manifest['expected_results']} trials, found {infantry}")
    if not missing and vehicles != manifest.get("expected_vehicle_results", 0):
        raise ValueError(f"Expected {manifest.get('expected_vehicle_results', 0)} vehicle trials, found {vehicles}")
    return begin, results


def summarize_vehicles(results, manifest):
    """Per (round, vehicle): how often the driver was hurt through the side, and how soon."""
    rounds = {row["classname"]: row for row in manifest["rounds"]}
    groups = defaultdict(list)
    for _, ammo, vehicle, _trial, first_hurt, state, damage, seated, values in (r for r in results if r[0] == "VEHICLE_RESULT"):
        groups[(ammo, vehicle)].append((first_hurt, state, damage, seated, values))
    rows = []
    for (ammo, vehicle), trials in groups.items():
        hurt = [first for first, *_ in trials if first > 0]
        rows.append({"cartridge": rounds[ammo]["cartridge"], "round": ammo, "round_role": rounds[ammo]["role"], "vehicle": vehicle,
                     "trials": len(trials), "crew_hurt": len(hurt), "first_hurt_shot": min(hurt) if hurt else None,
                     "crew_down": sum(state in ("unconscious", "dead") for _, state, *_ in trials),
                     "vehicle_damage_mean": round(statistics.fmean(damage for _, _, damage, *_ in trials), 4),
                     "seated": all(seated for *_, seated, _ in trials), "round_caliber": trials[0][4][1]})
    rows.sort(key=lambda r: (r["vehicle"], r["cartridge"], r["round_role"]))
    return rows


def summarize(results, manifest):
    """Median shots to incapacitate per (round, aim, wearable); -1 shots means it survived the cap."""
    meta = {("chest", row["classname"]): row for row in manifest["vests"]}
    meta.update({("head", row["classname"]): row for row in manifest["helmets"]})
    rounds = {row["classname"]: row for row in manifest["rounds"]}
    groups = defaultdict(list)
    for _, ammo, aim, gear, _trial, shots, state, first, values, _wearing in (r for r in results if r[0] == "RESULT"):
        groups[(ammo, aim, gear)].append((shots, state, first, values))
    rows = []
    for (ammo, aim, gear), trials in groups.items():
        downed = [shots for shots, *_ in trials if shots > 0]
        # Survivors count as "more than the cap" so they never lower the median.
        ranked = sorted(shots if shots > 0 else manifest["max_shots"] + 1 for shots, *_ in trials)
        item = meta[(aim, gear)]
        rows.append({"cartridge": rounds[ammo]["cartridge"], "round": ammo, "round_role": rounds[ammo]["role"],
                     "aim": aim, "wearable": gear or "(none)", "wearable_role": item["role"], "tier": item["tier"],
                     "armor": item.get("armor"), "passThrough": item.get("passThrough"),
                     "trials": len(trials), "incapacitated": len(downed),
                     "median_shots": statistics.median(ranked), "min_shots": min(downed) if downed else None,
                     "max_shots": max(downed) if downed else None,
                     "dead": sum(state == "dead" for _, state, *_ in trials),
                     "first_hit_damage_mean": round(statistics.fmean(first for _, _, first, _ in trials), 4),
                     "round_hit": trials[0][3][0], "round_caliber": trials[0][3][1]})
    rows.sort(key=lambda r: (r["aim"], r["cartridge"], r["round_role"], r["wearable_role"], r["armor"] or 0))
    return rows


def markdown(rows, begin, manifest, vehicle_rows=()):
    cap = manifest["max_shots"]
    shown = lambda value: f">{cap}" if value > cap else (f"{value:g}" if isinstance(value, (int, float)) else str(value))
    lines = ["# Range test results", "",
             f"Suite `{manifest['suite_id'][:12]}`, {manifest['trials']} trials per cell, cap {cap} shots, "
             "impact at each round's typicalSpeed from 3 m. Cells are median shots until unconscious or dead (ACE medical).",
             "", "ACE settings during the run: " + ", ".join(f"`{name}={value}`" for name, value in begin[10]), ""]
    for aim, title in (("chest", "Chest shots by vest"), ("head", "Head shots by helmet")):
        subset = [r for r in rows if r["aim"] == aim]
        rounds = sorted({(r["cartridge"], r["round_role"], r["round"]) for r in subset})
        lines += [f"## {title}", "", "| Wearable | Role | Armor / pass | " + " | ".join(f"{c} {role}" for c, role, _ in rounds) + " |",
                  "|---|---|---|" + "---:|" * len(rounds)]
        for gear in dict.fromkeys(r["wearable"] for r in subset):
            cells = {r["round"]: r for r in subset if r["wearable"] == gear}
            first = next(iter(cells.values()))
            lines.append(f"| `{gear}` | {first['wearable_role']} {first['tier']} | {first['armor']} / {first['passThrough']} | "
                         + " | ".join(shown(cells[name]["median_shots"]) if name in cells else "" for _, _, name in rounds) + " |")
        lines.append("")
    if vehicle_rows:
        rounds = sorted({(r["cartridge"], r["round_role"], r["round"]) for r in vehicle_rows})
        lines += ["## Side shots at a vehicle's driver", "",
                  f"Each cell: trials in which the driver was hurt, of {manifest.get('vehicle_trials')}, after "
                  f"{manifest.get('vehicle_shots')} shots through the left side from 3 m; the first hurting shot in brackets.", "",
                  "| Vehicle | " + " | ".join(f"{c} {role}" for c, role, _ in rounds) + " |", "|---|" + "---:|" * len(rounds)]
        for vehicle in dict.fromkeys(r["vehicle"] for r in vehicle_rows):
            cells = {r["round"]: r for r in vehicle_rows if r["vehicle"] == vehicle}
            text = lambda r: f"{r['crew_hurt']}/{r['trials']}" + (f" ({r['first_hurt_shot']})" if r["first_hurt_shot"] else "")
            lines.append(f"| `{vehicle}` | " + " | ".join(text(cells[name]) if name in cells else "" for _, _, name in rounds) + " |")
        lines.append("")
    lines += ["`before` rows carry today's mod values; `after` rows are the vanilla rung each maps to.",
              "Compare a before row with the after row of its target rung (see the manifest's proposed values).",
              "These are config outcomes on AI targets at point-blank range; they are not range falloff or player-damage measurements."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("rpt", type=Path)
    parser.add_argument("output", type=Path, help="new directory; existing directories are refused")
    parser.add_argument("--run")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "validation/range-test/manifest.json").read_text(encoding="utf-8"))
    run, records = read_records(args.rpt, args.run, b"A3BALRANGE")
    begin, results = validate(records, manifest)
    rows = summarize(results, manifest)
    vehicle_rows = summarize_vehicles(results, manifest)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "trials.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["round", "aim", "wearable", "trial", "shots", "state", "first_hit_damage", "round_values", "worn"])
        writer.writerows([r[1], r[2], r[3], r[4], r[5], r[6], r[7], json.dumps(r[8]), r[9]] for r in results if r[0] == "RESULT")
    with (args.output / "vehicle_trials.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["round", "vehicle", "trial", "first_hurt_shot", "crew_state", "vehicle_damage", "seated", "round_values"])
        writer.writerows([r[1], r[2], r[3], r[4], r[5], r[6], r[7], json.dumps(r[8])] for r in results if r[0] == "VEHICLE_RESULT")
    for name, table in (("summary.csv", rows), ("vehicle_summary.csv", vehicle_rows)):
        if table:
            with (args.output / name).open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(table[0]))
                writer.writeheader()
                writer.writerows(table)
    (args.output / "SUMMARY.md").write_text(markdown(rows, begin, manifest, vehicle_rows), encoding="utf-8")
    (args.output / "import-report.json").write_text(json.dumps(
        {"run": run, "suite_id": manifest["suite_id"], "trials": len(results), "missing_classes": begin[11],
         "ace_medical_loaded": begin[12], "settings": begin[10], "product_version": begin[8]}, indent=2), encoding="utf-8")
    print(json.dumps({"run": run, "trials": len(results), "cells": len(rows), "missing_classes": begin[11]}))
