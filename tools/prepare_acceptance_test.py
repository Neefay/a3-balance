"""Prepare the patched-game acceptance test, run with the balance pilot loaded.

Usage: python prepare_acceptance_test.py   (writes validation/acceptance-test/)
Unlike the range test, the mod items and rounds now carry their patched values, so each is
compared with the vanilla item or round it was mapped to: they should take the same number of shots.
Specialized rounds and a grenade check on uniforms are measured for review, not pass/fail.
"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from ammunition_policy import FAMILIES
from prepare_range_test import BEFORE_PER_KIND, HELMET_RUNGS, MAX_SHOTS, PREFERRED, SHOT_GAP, VEST_RUNGS, representatives
from prepare_remaining_captures import sqf

TRIALS = 5
BLAST_TRIALS = 5
BLAST_DISTANCE = 4
BLAST_AMMO = "GrenadeHand"
UNIFORMS = 2
SPECIAL_ROLES = ("armor_piercing_named", "enhanced_ball_named")


def preferred(names):
    rank = lambda n: next((i for i, prefix in enumerate(PREFERRED) if n.lower().startswith(prefix)), len(PREFERRED))
    return sorted(names, key=lambda n: (rank(n), len(n), n.lower()))


def plan(root):
    proposal = root / "proposal"
    ledger = json.loads((proposal / "change_ledger.json").read_text(encoding="utf-8"))
    anchors = {row["classname"]: row for row in json.loads((proposal / "anchors.json").read_text(encoding="utf-8"))}
    mapping = json.loads((proposal / "ammunition_mapping.json").read_text(encoding="utf-8"))

    def anchor_values(name, region):
        values = next(v for k, v in anchors[name]["protection"].items() if k.lower() == region.lower())
        lower = {k.lower(): v for k, v in values.items()}
        return lower.get("armor"), lower.get("passthrough")

    targets = {"chest": [{"classname": "", "role": "reference", "tier": "no vest", "armor": 0, "passThrough": None}],
               "head": [{"classname": "", "role": "reference", "tier": "no helmet", "armor": 0, "passThrough": None}]}
    for aim, region, rungs in (("chest", "Chest", VEST_RUNGS), ("head", "Head", HELMET_RUNGS)):
        targets[aim] += [{"classname": name, "role": "reference", "tier": tier, **dict(zip(("armor", "passThrough"), anchor_values(name, region)))}
                         for tier, name in rungs]
    # Each patched item is compared with the reference carrying its proposed values; its own anchor is added if none does.
    for aim, kind, region in (("chest", "vest", "Chest"), ("head", "headgear", "Head")):
        for item in representatives(root, ledger, kind, region, BEFORE_PER_KIND):
            values = (item["proposed_armor"], item["proposed_passThrough"])
            match = next((t for t in targets[aim] if t["role"] == "reference" and (t["armor"], t["passThrough"]) == values), None)
            if match is None:
                match = {"classname": item["anchor"], "role": "reference", "tier": item["tier"],
                         **dict(zip(("armor", "passThrough"), anchor_values(item["anchor"], region)))}
                targets[aim].append(match)
            targets[aim].append({"classname": item["classname"], "role": "patched", "tier": item["tier"], "armor": values[0],
                                 "passThrough": values[1], "compare_with": match["classname"], "anchor": item["anchor"],
                                 "items_with_these_values": item["items_with_these_values"]})
    # Uniforms: the patched units' changes are explosion shielding, so they get a grenade check against the vanilla uniform.
    unit_edits = defaultdict(int)
    for row in ledger:
        if row["kind"] == "uniform_unit":
            unit_edits[row["classname"].lower()] += 1
    wearables = json.loads((proposal / "wearable_targets.json").read_text(encoding="utf-8"))
    uniforms = [row for row in wearables if row["kind"] == "uniform" and row["field_changes"] and row["reference_class"] == "U_B_CombatUniform_mcam"]
    picked = preferred([row["classname"] for row in uniforms])[:UNIFORMS]
    # Chest shots in uniforms: a patched one against the vanilla combat uniform, and a civilian one whose held
    # globals (armorStructural 0.4 against vanilla 4) are measured against vanilla's polo shirt.
    civilian = preferred([row["classname"] for row in wearables if row["kind"] == "uniform" and row["status"] == "review_held_target_fields"
                          and any(f["reason"] == "civilian_globals_need_in_game_test" for f in row["held_fields"])])[:1]
    targets["uniform"] = [{"classname": "U_B_CombatUniform_mcam", "role": "reference", "tier": "vanilla uniform"},
                          {"classname": "U_C_Poloshirt_blue", "role": "reference", "tier": "vanilla civilian"},
                          {"classname": picked[0], "role": "patched", "tier": "ordinary clothing", "compare_with": "U_B_CombatUniform_mcam"}]
    targets["uniform"] += [{"classname": name, "role": "held", "tier": "civilian (globals held)", "compare_with": "U_C_Poloshirt_blue"} for name in civilian]
    blast = [{"classname": "", "role": "reference", "tier": "vanilla uniform"}]
    blast += [{"classname": name, "role": "patched", "tier": "ordinary clothing", "compare_with": ""} for name in picked]

    rounds = []
    for _, label, vanilla, mod_ball in FAMILIES:
        rounds.append({"cartridge": label, "classname": vanilla, "role": "reference", "ladder_role": "ball_named"})
        rounds.append({"cartridge": label, "classname": mod_ball, "role": "patched", "ladder_role": "ball_named", "compare_with": vanilla})
        for ladder_role in SPECIAL_ROLES:
            names = [row["classname"] for row in mapping if row["cartridge"] == label and row["ladder_role"] == ladder_role
                     and row["status"] == "proposed_change" and not row["tracer_name_flag"]]
            if names:
                rounds.append({"cartridge": label, "classname": preferred(names)[0], "role": "special", "ladder_role": ladder_role,
                               "compare_with": vanilla})
    cells = []
    for round_ in rounds:
        for aim in ("chest", "head", "uniform"):
            for target in targets[aim]:
                if aim == "uniform" and round_["role"] != "patched":
                    continue
                # Vanilla balls set the references; patched balls meet every target; special rounds only meet vest references.
                if round_["role"] == "patched" or (target["role"] == "reference" and (round_["role"] == "reference" or aim == "chest")):
                    cells.append([round_["cartridge"], round_["classname"], aim, target["classname"]])
    return rounds, targets, blast, cells


def prepare(root):
    rounds, targets, blast, cells = plan(root)
    template = (root / "acceptance_test.template.sqf").read_text(encoding="utf-8")
    identity = {"version": 1, "rounds": rounds, "targets": targets, "blast": blast, "cells": cells, "trials": TRIALS,
                "max_shots": MAX_SHOTS, "shot_gap": SHOT_GAP, "blast_trials": BLAST_TRIALS, "blast_distance": BLAST_DISTANCE,
                "blast_ammo": BLAST_AMMO, "template_sha256": hashlib.sha256(template.encode()).hexdigest()}
    suite_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    script = (template.replace("__SUITE_ID__", suite_id).replace("__CELLS__", sqf(cells))
              .replace("__BLAST__", sqf([row["classname"] for row in blast]))
              .replace("__TRIALS__", str(TRIALS)).replace("__MAX_SHOTS__", str(MAX_SHOTS)).replace("__SHOT_GAP__", str(SHOT_GAP))
              .replace("__BLAST_TRIALS__", str(BLAST_TRIALS)).replace("__BLAST_DISTANCE__", str(BLAST_DISTANCE))
              .replace("__BLAST_AMMO__", sqf(BLAST_AMMO)))
    destination = root / "validation" / "acceptance-test"
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "acceptance_test.sqf"
    path.write_text(script, encoding="utf-8", newline="")
    manifest = {**identity, "suite_id": suite_id, "expected_results": len(cells) * TRIALS,
                "expected_blast_results": len(blast) * BLAST_TRIALS,
                "script": {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                "status": "Prepared; runs inside the balance pilot session (requires the pilot loaded)."}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"suite_id": suite_id, "rounds": len(rounds), "cells": len(cells), "expected_results": manifest["expected_results"],
            "blast_results": manifest["expected_blast_results"], "targets": {aim: len(rows) for aim, rows in targets.items()}}


if __name__ == "__main__":
    print(json.dumps(prepare(Path(__file__).resolve().parent), indent=2))
