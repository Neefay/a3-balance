"""Prepare the shots-to-incapacitate range test from the current proposal.

"After" items are the vanilla rung anchors themselves, so the test needs no patch:
each rung is compared with representative mod items carrying today's values.
"""
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path

from ammunition_policy import FAMILIES
from prepare_remaining_captures import sqf

TRIALS = 6
MAX_SHOTS = 12
SHOT_GAP = 0.35
VEST_RUNGS = [("soft", "V_TacVest_khk"), ("flak", "V_TacVest_blk_POLICE"), ("light carrier", "V_PlateCarrier1_rgr"),
              ("plate", "V_PlateCarrier2_rgr"), ("heavy", "V_PlateCarrierSpec_rgr")]
HELMET_RUNGS = [("steel (light)", "H_HelmetB_light"), ("composite", "H_HelmetB"), ("crew", "H_HelmetCrew_I"),
                ("heavy visored", "H_HelmetSpecB")]
BEFORE_PER_KIND = 5
# Light-armor check for shared vehicle MG rounds: RHS/3CB light armor and soft vehicles,
# with a vanilla APC and car as references for how vanilla rounds treat vanilla hulls.
VEHICLES = ["rhs_btr80_msv", "rhs_bmp2_msv", "rhsusf_m113_usarmy", "rhs_tigr_msv", "rhsusf_m1025_w",
            "UK3CB_TKA_O_Hilux_Dshkm", "O_APC_Wheeled_02_rcws_v2_F", "C_Offroad_01_F"]
VEHICLE_TRIALS = 2
VEHICLE_SHOTS = 8


PREFERRED = ("rhsusf_", "rhs_", "uk3cb_", "brm_", "h_simc", "v_simc", "sns_")


def observed(root, kind, region):
    """Observed (armor, passThrough) per class from the chart exports."""
    source = "headgear.csv" if kind == "headgear" else "vest_regions.csv"
    with (root / "chart-data" / source).open(encoding="utf-8-sig", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row["region"].lower() == region.lower()]
    number = lambda value: float(value) if value not in ("", None) else None
    return {row["classname"]: (number(row["armor"]), number(row["pass_through"])) for row in rows}


def representatives(root, ledger, kind, region, limit):
    """One public item per distinct observed (armor, passThrough); every target anchor stays represented."""
    values = observed(root, kind, region)
    proposed = defaultdict(dict)
    anchor_of = {}
    for row in ledger:
        if row["kind"] == kind and len(row["path"]) >= 2 and row["path"][-2].lower() == region.lower():
            proposed[row["classname"]][row["path"][-1].lower()] = row["proposed"]
            anchor_of[row["classname"]] = (row["rule"], row["anchors"][0])
    groups = defaultdict(list)
    for name in proposed:
        if values.get(name, (None,))[0] is not None:
            groups[values[name]].append(name)
    ranked = sorted(groups, key=lambda key: -len(groups[key]))
    chosen = []
    # Webbing has no chest plate to test; its rung is the unarmored baseline.
    for anchor in sorted({anchor for _, anchor in anchor_of.values()} - {"V_Chestrig_khk"}):
        best = max((key for key in ranked if any(anchor_of[n][1] == anchor for n in groups[key])),
                   key=lambda key: sum(anchor_of[n][1] == anchor for n in groups[key]), default=None)
        if best is not None and best not in chosen:
            chosen.append(best)
    chosen += [key for key in ranked if key not in chosen][:max(0, limit - len(chosen))]
    picked = []
    for armor, through in chosen:
        rank = lambda n: next((i for i, prefix in enumerate(PREFERRED) if n.lower().startswith(prefix)), len(PREFERRED))
        names = sorted(groups[(armor, through)], key=lambda n: (rank(n), len(n), n.lower()))
        name = names[0]
        picked.append({"classname": name, "role": "before", "tier": anchor_of[name][0], "anchor": anchor_of[name][1],
                       "items_with_these_values": len(names), "armor": armor, "passThrough": through,
                       "proposed_by_anchor": dict(Counter(anchor_of[n][1] for n in names)),
                       "proposed_armor": proposed[name].get("armor", armor),
                       "proposed_passThrough": proposed[name].get("passthrough", through)})
    return picked


def plan(root):
    proposal = root / "proposal"
    ledger = json.loads((proposal / "change_ledger.json").read_text(encoding="utf-8"))
    anchors = {row["classname"]: row for row in json.loads((proposal / "anchors.json").read_text(encoding="utf-8"))}

    def anchor_values(name, region):
        values = next(v for k, v in anchors[name]["protection"].items() if k.lower() == region.lower())
        lower = {k.lower(): v for k, v in values.items()}
        return lower.get("armor"), lower.get("passthrough")

    vests = [{"classname": "", "role": "baseline", "tier": "no vest", "armor": 0, "passThrough": None}]
    vests += [{"classname": name, "role": "after", "tier": tier, **dict(zip(("armor", "passThrough"), anchor_values(name, "Chest")))}
              for tier, name in VEST_RUNGS]
    vests += representatives(root, ledger, "vest", "Chest", BEFORE_PER_KIND)
    helmets = [{"classname": "", "role": "baseline", "tier": "no helmet", "armor": 0, "passThrough": None}]
    helmets += [{"classname": name, "role": "after", "tier": tier, **dict(zip(("armor", "passThrough"), anchor_values(name, "Head")))}
                for tier, name in HELMET_RUNGS]
    helmets += representatives(root, ledger, "headgear", "Head", BEFORE_PER_KIND)
    rounds = []
    for _, label, vanilla, mod_ball in FAMILIES:
        rounds.append({"cartridge": label, "classname": vanilla, "role": "after"})
        rounds.append({"cartridge": label, "classname": mod_ball, "role": "before"})
    return rounds, vests, helmets


def prepare(root):
    rounds, vests, helmets = plan(root)
    targets = [["chest", row["classname"]] for row in vests] + [["head", row["classname"]] for row in helmets]
    template = (root / "range_test.template.sqf").read_text(encoding="utf-8")
    identity = {"version": 2, "rounds": rounds, "vests": vests, "helmets": helmets, "trials": TRIALS,
                "max_shots": MAX_SHOTS, "shot_gap": SHOT_GAP, "vehicles": VEHICLES,
                "vehicle_trials": VEHICLE_TRIALS, "vehicle_shots": VEHICLE_SHOTS,
                "template_sha256": hashlib.sha256(template.encode()).hexdigest()}
    suite_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    script = (template.replace("__SUITE_ID__", suite_id)
              .replace("__ROUNDS__", sqf([[r["cartridge"], r["classname"]] for r in rounds]))
              .replace("__TARGETS__", sqf(targets))
              .replace("__TRIALS__", str(TRIALS)).replace("__MAX_SHOTS__", str(MAX_SHOTS))
              .replace("__SHOT_GAP__", str(SHOT_GAP)).replace("__VEHICLES__", sqf(VEHICLES))
              .replace("__VEHICLE_TRIALS__", str(VEHICLE_TRIALS)).replace("__VEHICLE_SHOTS__", str(VEHICLE_SHOTS)))
    destination = root / "validation" / "range-test"
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / "range_test.sqf"
    path.write_text(script, encoding="utf-8", newline="")
    manifest = {**identity, "suite_id": suite_id, "expected_results": len(rounds) * len(targets) * TRIALS,
                "expected_vehicle_results": len(rounds) * len(VEHICLES) * VEHICLE_TRIALS,
                "script": {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
                "status": "Prepared; requires one full-preset Eden preview. Spawns test units, changes no config."}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"suite_id": suite_id, "rounds": len(rounds), "chest_targets": len(vests), "head_targets": len(helmets),
            "expected_results": manifest["expected_results"], "expected_vehicle_results": manifest["expected_vehicle_results"],
            "before_items": Counter(row["role"] for row in vests + helmets)["before"]}


if __name__ == "__main__":
    print(json.dumps(prepare(Path(__file__).resolve().parent), indent=2))
