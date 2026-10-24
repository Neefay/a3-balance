"""Import one balance pilot session RPT, config checks and acceptance test, into a NEW directory.

Usage: python import_pilot_session.py <rpt> <output_dir> [--pilot balance-pilot]
Writes verification-result.json, acceptance trials/summary CSVs, ACCEPTANCE.md and session-report.json.
The session passes when every config check passes and every patched item and round takes the
same shots (within TOLERANCE) as the vanilla item or round it was mapped to.
"""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import statistics

from import_balance_verification import validate as validate_config
from import_clean_capture import read_records

TOLERANCE = 1
BLAST_TOLERANCE = 0.3


def validate(records, manifest):
    suite = manifest["suite_id"]
    if len(records) < 2 or records[0][:3] != ["BEGIN_ACCEPT", 1, suite] or records[-1][:3] != ["END_ACCEPT", 1, suite]:
        raise ValueError("Missing/mismatched acceptance-test boundaries or suite ID")
    begin, end, results = records[0], records[-1], records[1:-1]
    if end[3] != len(records) or end[4] != len(results) or any(r[0] not in ("RESULT", "BLAST") for r in results):
        raise ValueError("Acceptance records disagree with the END summary")
    shots = sum(r[0] == "RESULT" for r in results)
    if not begin[10] and (shots, len(results) - shots) != (manifest["expected_results"], manifest["expected_blast_results"]):
        raise ValueError(f"Expected {manifest['expected_results']} + {manifest['expected_blast_results']} trials, found {shots} + {len(results) - shots}")
    return begin, results


def summarize(results, manifest):
    """Median shots to incapacitate per (round, aim, wearable); survivors count as more than the cap."""
    meta = {(aim, row["classname"]): row for aim, rows in manifest["targets"].items() for row in rows}
    rounds = {row["classname"]: row for row in manifest["rounds"]}
    groups = defaultdict(list)
    for _, ammo, aim, gear, _trial, shots, state, _first, values, _worn in (r for r in results if r[0] == "RESULT"):
        groups[(ammo, aim, gear)].append((shots, state, values))
    rows = []
    for (ammo, aim, gear), trials in groups.items():
        ranked = sorted(shots if shots > 0 else manifest["max_shots"] + 1 for shots, *_ in trials)
        item = meta[(aim, gear)]
        rows.append({"cartridge": rounds[ammo]["cartridge"], "round": ammo, "round_role": rounds[ammo]["role"],
                     "ladder_role": rounds[ammo]["ladder_role"], "aim": aim, "wearable": gear, "wearable_role": item["role"],
                     "tier": item["tier"], "armor": item.get("armor"), "passThrough": item.get("passThrough"),
                     "trials": len(trials), "incapacitated": sum(shots > 0 for shots, *_ in trials),
                     "median_shots": statistics.median(ranked), "dead": sum(state == "dead" for _, state, _ in trials),
                     "round_hit": trials[0][2][0], "round_caliber": trials[0][2][1], "round_speed": trials[0][2][2]})
    return rows


def summarize_blast(results):
    groups = defaultdict(list)
    for _, uniform, _trial, state, total, _parts, damage, worn in (r for r in results if r[0] == "BLAST"):
        groups[uniform].append((state, total, damage, worn))
    return [{"uniform": uniform or "(vanilla)", "worn": trials[0][3], "trials": len(trials),
             "downed": sum(state != "standing" for state, *_ in trials),
             "mean_body_damage": round(statistics.fmean(total for _, total, *_ in trials), 4),
             "mean_engine_damage": round(statistics.fmean(damage for *_, damage, _ in trials), 4)} for uniform, trials in groups.items()]


def compare(rows, blast, manifest):
    cap = manifest["max_shots"]
    cell = {(r["round"], r["aim"], r["wearable"]): r["median_shots"] for r in rows}
    same = lambda a, b: (a > cap and b > cap) or abs(a - b) <= TOLERANCE
    targets = {(aim, row["classname"]): row for aim, rows_ in manifest["targets"].items() for row in rows_}
    checks, held = [], []
    for round_ in manifest["rounds"]:
        if round_["role"] == "patched":
            # A patched mod ball against each vanilla reference target, next to the vanilla ball.
            for (aim, gear), target in targets.items():
                ours, reference = cell.get((round_["classname"], aim, gear)), cell.get((round_["compare_with"], aim, gear))
                if target["role"] == "reference" and ours is not None and reference is not None:
                    checks.append({"kind": "round", "subject": round_["classname"], "against": round_["compare_with"], "aim": aim,
                                   "wearable": gear or "(none)", "shots": ours, "reference_shots": reference, "verdict": "match" if same(ours, reference) else "differs"})
            # Each patched item against the reference carrying its values, under the same patched round. Held items
            # (civilian globals left at mod values) are measured the same way but reported for review only.
            for (aim, gear), target in targets.items():
                if target["role"] in ("patched", "held"):
                    ours, reference = cell.get((round_["classname"], aim, gear)), cell.get((round_["classname"], aim, target["compare_with"]))
                    if ours is not None and reference is not None:
                        (checks if target["role"] == "patched" else held).append(
                            {"kind": "item" if target["role"] == "patched" else "held", "subject": gear, "against": target["compare_with"], "aim": aim,
                             "round": round_["classname"], "shots": ours, "reference_shots": reference, "verdict": "match" if same(ours, reference) else "differs"})
    order = []
    for round_ in manifest["rounds"]:
        if round_["role"] == "special":
            for (aim, gear), target in targets.items():
                ours, ball = cell.get((round_["classname"], aim, gear)), cell.get((round_["compare_with"], aim, gear))
                if aim == "chest" and target["role"] == "reference" and ours is not None and ball is not None:
                    # Specialized rounds should need no more shots than ball; review, not pass/fail.
                    order.append({"round": round_["classname"], "ladder_role": round_["ladder_role"], "wearable": gear or "(none)",
                                  "shots": ours, "ball_shots": ball, "verdict": "in order" if ours <= ball or (ours > cap and ball > cap) else "needs more shots than ball"})
    vanilla = next((row for row in blast if row["uniform"] == "(vanilla)"), None)
    blasts = []
    for row in blast:
        if vanilla and row is not vanilla:
            reference = vanilla["mean_body_damage"]
            close = abs(row["mean_body_damage"] - reference) <= BLAST_TOLERANCE * max(reference, 1e-6)
            blasts.append({**row, "vanilla_mean_body_damage": reference, "verdict": "similar" if close else "differs (review)"})
    return checks, order, blasts, held


def markdown(config, checks, order, blasts, held, begin, manifest):
    cap = manifest["max_shots"]
    shown = lambda v: f">{cap}" if v > cap else f"{v:g}"
    passed = config["passed"] and all(c["verdict"] == "match" for c in checks)
    lines = ["# Balance pilot session", "", f"**{'PASS' if passed else 'NEEDS REVIEW'}**", "",
             f"- Config checks: {'passed' if config['passed'] else 'FAILED'} ({config['checked_classes']:,} classes, "
             f"{config['checked_fields']:,} entries, {config['failure_count']} failures).",
             f"- Patched rounds and items matching their vanilla reference (within {TOLERANCE} shot): "
             f"{sum(c['verdict'] == 'match' for c in checks)} of {len(checks)}.",
             f"- Specialized rounds in order against vests: {sum(o['verdict'] == 'in order' for o in order)} of {len(order)} (review only).",
             f"- Grenade check, uniforms similar to vanilla: {sum(b['verdict'] == 'similar' for b in blasts)} of {len(blasts)} (review only).",
             f"- Held civilian uniform (armorStructural 0.4) matching vanilla's polo: {sum(h['verdict'] == 'match' for h in held)} of {len(held)} "
             "(review only: if all match, the held field does not matter under ACE).", "",
             "ACE settings: " + ", ".join(f"`{n}={v}`" for n, v in begin[9]), ""]
    differ = [c for c in checks if c["verdict"] != "match"]
    if differ:
        lines += ["## Differences", "", "| Kind | Subject | Reference | Aim | Wearable / round | Shots | Reference shots |", "|---|---|---|---|---|---:|---:|"]
        lines += [f"| {c['kind']} | `{c['subject']}` | `{c['against']}` | {c['aim']} | `{c.get('wearable', c.get('round'))}` | {shown(c['shots'])} | {shown(c['reference_shots'])} |" for c in differ]
        lines.append("")
    lines += ["## Patched mod ball against the vanilla ball", "", "| Round | Aim | Wearable | Shots | Vanilla ball |", "|---|---|---|---:|---:|"]
    lines += [f"| `{c['subject']}` | {c['aim']} | `{c['wearable']}` | {shown(c['shots'])} | {shown(c['reference_shots'])} |" for c in checks if c["kind"] == "round"]
    lines += ["", "## Patched items against their vanilla reference", "", "| Item | Reference | Round | Shots | Reference |", "|---|---|---|---:|---:|"]
    lines += [f"| `{c['subject']}` | `{c['against']}` | `{c['round']}` | {shown(c['shots'])} | {shown(c['reference_shots'])} |" for c in checks if c["kind"] == "item"]
    lines += ["", "## Specialized rounds against vanilla vests", "", "| Round | Type | Vest | Shots | Ball | |", "|---|---|---|---:|---:|---|"]
    lines += [f"| `{o['round']}` | {o['ladder_role'].replace('_named', '').replace('_', ' ')} | `{o['wearable']}` | {shown(o['shots'])} | {shown(o['ball_shots'])} | {o['verdict']} |" for o in order]
    lines += ["", "## Held civilian uniform against vanilla's polo shirt", "", "| Uniform | Reference | Round | Shots | Reference | |", "|---|---|---|---:|---:|---|"]
    lines += [f"| `{h['subject']}` | `{h['against']}` | `{h['round']}` | {shown(h['shots'])} | {shown(h['reference_shots'])} | {h['verdict']} |" for h in held]
    lines += ["", f"## Grenade at {manifest['blast_distance']} m", "", "| Uniform | Downed | Mean body damage | Vanilla | |", "|---|---:|---:|---:|---|"]
    lines += [f"| `{b['uniform']}` | {b['downed']}/{b['trials']} | {b['mean_body_damage']:g} | {b['vanilla_mean_body_damage']:g} | {b['verdict']} |" for b in blasts]
    lines += ["", f"Cells are median shots of {manifest['trials']} trials until unconscious or dead (ACE medical), cap {cap}, impact at the round's",
              "typicalSpeed from 3 m. These are config outcomes on AI targets at point-blank range."]
    return "\n".join(lines) + "\n", passed


def write_csv(path, rows):
    if rows:
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(key for row in rows for key in row)))
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("rpt", type=Path)
    parser.add_argument("output", type=Path, help="new directory; existing directories are refused")
    parser.add_argument("--pilot", default="balance-pilot")
    parser.add_argument("--run", help="acceptance run ID when the RPT holds more than one")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    pilot = json.loads((root / args.pilot / "manifest.json").read_text())
    accept = json.loads((root / "validation/acceptance-test/manifest.json").read_text(encoding="utf-8"))
    if pilot["session"]["acceptance_suite_id"] != accept["suite_id"]:
        raise ValueError("The pilot was built with a different acceptance suite")
    config = validate_config(args.rpt, pilot)
    run, records = read_records(args.rpt, args.run, b"A3BALACCEPT")
    begin, results = validate(records, accept)
    if begin[12] != pilot["build_id"]:
        raise ValueError("The acceptance test ran without this pilot build loaded")
    rows = summarize(results, accept)
    blast = summarize_blast(results)
    checks, order, blasts, held = compare(rows, blast, accept)
    text, passed = markdown(config, checks, order, blasts, held, begin, accept)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "verification-result.json").write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    with (args.output / "trials.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["kind", "fields"])
        writer.writerows([r[0], json.dumps(r[1:])] for r in results)
    write_csv(args.output / "summary.csv", rows)
    write_csv(args.output / "blast.csv", blast)
    write_csv(args.output / "checks.csv", checks + order + held)
    (args.output / "ACCEPTANCE.md").write_text(text, encoding="utf-8")
    report = {"passed": passed, "config_passed": config["passed"], "acceptance_run": run, "pilot_build_id": pilot["build_id"],
              "suite_id": accept["suite_id"], "trials": len(results), "missing_classes": begin[10],
              "matches": sum(c["verdict"] == "match" for c in checks), "checks": len(checks), "settings": begin[9], "product_version": begin[7]}
    (args.output / "session-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("passed", "config_passed", "matches", "checks", "trials", "missing_classes")}))
    if not passed:
        raise SystemExit(1)
