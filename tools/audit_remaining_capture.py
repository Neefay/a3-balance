"""Assess imported supplemental snapshots without changing observations or proposals."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
import json
import math
from pathlib import Path
import sqlite3


def encode(value):
    return json.dumps(value, separators=(",", ":"))


def same(left, right):
    if type(left) in (int, float) and type(right) in (int, float):
        return math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-6)
    return type(left) is type(right) and left == right


def assess(root, full_folder, clean_folder):
    full_report = json.loads((full_folder / "import-report.json").read_text())
    clean_report = json.loads((clean_folder / "import-report.json").read_text())
    if full_report["status"] != "complete" or clean_report["status"] != "complete":
        raise ValueError("Both snapshots must be complete")
    if full_report["mode"] != "full" or clean_report["mode"] != "clean":
        raise ValueError("Wrong snapshot modes")
    result = {"full_import": str(full_folder), "clean_import": str(clean_folder),
              "capture_complete": True, "full_sections": full_report["sections"],
              "clean_sections": clean_report["sections"],
              "helmet_gate_passed": full_report.get("pilot_verification", {}).get("passed", False),
              "helmet_summary": full_report.get("pilot_summary"),
              "full_product_version": full_report["product_version"],
              "clean_product_version": clean_report["product_version"],
              "notes": ["No observations or proposals were changed.",
                        "Config fields do not establish effects on damage. Civilian globals and legacy uniform fields remain held.",
                        "Configured vehicle use is a deferral signal; lack of a link alone does not prove handheld-only use."]}
    with closing(sqlite3.connect(full_folder / "snapshot.sqlite")) as db:
        pilot_classes = db.execute("SELECT classname FROM configs WHERE section='CfgPatches' AND classname='a3bal_helmets_pilot'").fetchall()
        result["helmet_patch_present"] = bool(pilot_classes)
        proposal = root / "proposal"
        ledger = json.loads((proposal / "change_ledger.json").read_text())
        counts = defaultdict(Counter)
        differences = []
        for edit in ledger:
            row = db.execute("SELECT kind,value FROM fields WHERE section=? AND classname=? AND path=?",
                             (edit["section"], edit["classname"], encode(edit["path"]))).fetchone()
            if row is None or row[0] == "missing":
                status, actual = "missing", None
            else:
                actual = json.loads(row[1])
                status = "matches_old" if same(actual, edit["old"]) else "matches_proposed" if same(actual, edit["proposed"]) else "differs_from_both"
            counts[edit["kind"]][status] += 1
            if status in {"missing", "differs_from_both"}:
                differences.append({"section": edit["section"], "classname": edit["classname"], "path": edit["path"],
                                    "old": edit["old"], "proposed": edit["proposed"], "actual": actual,
                                    "actual_kind": row[0] if row else "not_captured", "status": status})
        result["ledger_field_statuses"] = {kind: dict(statuses) for kind, statuses in counts.items()}
        result["ledger_drift"] = differences
        probes = {(s.lower(), n.lower(), tuple(x.lower() for x in json.loads(p))): json.loads(data)
                  for s, n, p, data in db.execute("SELECT section,classname,path,data FROM probes")}
        result["probe_count"] = len(probes)
        result["probe_node_types"] = dict(Counter(node[0] for node in probes.values()))
        guards = json.loads((proposal / "wearable_preservation_guards.json").read_text())
        missing = []
        for row in guards:
            if row["present"]:
                continue
            key = (row["section"].lower(), row["classname"].lower(), tuple(p.lower() for p in row["path"]))
            missing.append({"section": row["section"], "classname": row["classname"], "path": row["path"], "captured_node": probes.get(key)})
        result["previous_missing_vest_paths"] = missing
        result["previous_missing_path_types"] = dict(Counter(row["captured_node"][0] if row["captured_node"] else "not_captured" for row in missing))
        assessments = json.loads((proposal / "wearable_assessments.json").read_text())
        legacy = []
        for row in assessments:
            if row["status"] != "review_uniform_item_fields":
                continue
            values = db.execute("""SELECT path,kind,value FROM fields
                WHERE section='CfgWeapons' AND classname=?
                AND (path LIKE ? OR path IN ('["armor"]','["passThrough"]','["explosionShielding"]'))""",
                                (row["classname"], '["ItemInfo",%')).fetchall()
            armor = [{"path": json.loads(path), "kind": kind, "value": json.loads(value)}
                     for path, kind, value in values if json.loads(path)[-1].lower() in {"armor", "passthrough", "explosionshielding"}]
            legacy.append({"classname": row["classname"], "unit_class": row.get("unit_class"), "observed_fields": armor, "decision": "held"})
        result["legacy_uniform_items"] = legacy
        result["vehicle_linked_projectiles_direct_magazines"] = db.execute("SELECT count(DISTINCT ammo) FROM projectile_vehicle_magazines").fetchone()[0]
        result["weapon_magazine_edges"] = db.execute("SELECT count(*) FROM weapon_magazines").fetchone()[0]
        result["vehicle_mount_nodes"] = db.execute("SELECT count(*) FROM mount_nodes").fetchone()[0]
        result["vehicle_mount_edges"] = db.execute("SELECT count(*) FROM mounts").fetchone()[0]
        db.execute("ATTACH DATABASE ? AS clean", (str(clean_folder / "snapshot.sqlite"),))
        damage_fields = ('["hit"]', '["caliber"]', '["typicalSpeed"]', '["airFriction"]')
        ammo_drift = []
        for name, path, old_kind, old_value, new_kind, new_value in db.execute("""
            SELECT f.classname,f.path,f.kind,f.value,c.kind,c.value FROM fields f
            JOIN clean.fields c ON c.section=f.section AND c.classname=f.classname AND c.path=f.path
            WHERE f.section='CfgAmmo' AND f.path IN (?,?,?,?)
            ORDER BY f.classname,f.path
        """, damage_fields):
            old_value, new_value = json.loads(old_value), json.loads(new_value)
            if old_kind != new_kind or not same(old_value, new_value):
                ammo_drift.append({"classname": name, "path": json.loads(path), "full_kind": old_kind,
                                   "full": old_value, "clean_kind": new_kind, "clean": new_value})
        result["vanilla_named_ammo_field_drift"] = ammo_drift
        # Compare class sets against the original export without loading property
        # trees for all classes at once. This identifies preset/config drift.
        original = defaultdict(set)
        with (root / "data-recovered/configs.relevant.jsonl").open(encoding="utf-8") as source:
            for line in source:
                row = json.loads(line)
                original[row["section"]].add(row["classname"].lower())
        current = defaultdict(set)
        for section, name in db.execute("SELECT section,classname FROM configs"):
            current[section].add(name.lower())
        result["original_class_set_comparison"] = {
            section: {"old": len(names), "current": len(current[section]),
                      "added": len(current[section] - names), "absent": len(names - current[section]),
                      "absent_classes": sorted(names - current[section])}
            for section, names in original.items()}
    return result


def markdown(result):
    lines = ["# Supplemental capture assessment", "",
             "Both batch captures imported completely and are secured in the RPT archive.",
             "Original observations and proposals remain unchanged.", "",
             f"Helmet release gate: **{'passed' if result['helmet_gate_passed'] else 'NOT verified'}**.",
             f"Pilot patch present in CfgPatches: **{result['helmet_patch_present']}**.",
             f"Pilot footer summary: `{result['helmet_summary']}`.", "",
             "## Capture coverage", "",
             "| Section | Full | Clean |", "|---|---:|---:|"]
    for section, count in result["full_sections"].items():
        lines.append(f"| {section} | {count:,} | {result['clean_sections'].get(section, 0):,} |")
    lines += ["", f"Explicit probes: {result['probe_count']:,}. Node types: `{result['probe_node_types']}`.",
              f"Weapon/magazine edges: {result['weapon_magazine_edges']:,}. Vehicle mount nodes: {result['vehicle_mount_nodes']:,}.",
              f"Previously missing vest path types now: `{result['previous_missing_path_types']}`.",
              f"Legacy uniform item cases captured: {len(result['legacy_uniform_items'])}; all remain held.", "",
              "## Original proposal compared with the running full preset", "",
              "| Kind | Matches original | Matches proposed | Other value | Missing |", "|---|---:|---:|---:|---:|"]
    for kind, counts in result["ledger_field_statuses"].items():
        lines.append(f"| {kind} | {counts.get('matches_old', 0):,} | {counts.get('matches_proposed', 0):,} | {counts.get('differs_from_both', 0):,} | {counts.get('missing', 0):,} |")
    lines += ["", "Matching a proposed value does not show that the pilot was loaded.",
              f"Vanilla-named ammo differences across hit/caliber/typicalSpeed/airFriction: {len(result['vanilla_named_ammo_field_drift'])}.",
              "These are comparison results, not new edits or approved targets.", "",
              "## Next actions", "",
              "The large exports do not need repeating. The helmet addon must be enabled and its standalone verifier run before other equipment patches are added. Keep using the original full preset; preserve the RPT including A3BALPILOT records.",
              "Review config drift, missing descendant paths and uniform evidence offline. The civilian and legacy uniform mechanics still require controlled tests; absent fields are not zero. Complete the vehicle/weapon/pylon use audit before admitting ammo edits.", "",
              "Full details, including class-set differences, are in the adjacent JSON. Queryable observations remain in each imported snapshot.sqlite."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("full_folder", type=Path)
    parser.add_argument("clean_folder", type=Path)
    parser.add_argument("output_prefix", type=Path)
    args = parser.parse_args()
    result = assess(Path(__file__).resolve().parent, args.full_folder, args.clean_folder)
    for extension, content in (("json", json.dumps(result, ensure_ascii=False, indent=2)), ("md", markdown(result))):
        with args.output_prefix.with_suffix("." + extension).open("x", encoding="utf-8") as stream:
            stream.write(content)
    print(json.dumps({k: result[k] for k in ("capture_complete", "helmet_gate_passed", "helmet_patch_present", "ledger_field_statuses", "previous_missing_path_types")}))
