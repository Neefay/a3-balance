"""Prepare two bounded captures: full preset + pilot, and expanded clean references."""
import hashlib
import json
from pathlib import Path

from build_helmet_pilot import literal


def sqf(value):
    if isinstance(value, list):
        return "[" + ",".join(sqf(v) for v in value) + "]"
    return literal(value)

WEAPON_FIELDS = """displayName scope scopeArsenal type simulation baseWeapon model
mass inertia initSpeed magazines magazineWell muzzles ItemInfo armor passThrough
HitPoints HitpointsProtectionInfo""".split()
VEHICLE_FIELDS = """displayName scope scopeArsenal simulation model uniformClass
armor armorStructural explosionShielding damageResistance impactDamageMultiplier
armorHead armorBody armorHands armorLegs passThrough weapons magazines
TransportWeapons TransportMagazines""".split()


def prepare(root):
    proposal = root / "proposal"
    targets = json.loads((proposal / "wearable_targets.json").read_text())
    assessments = json.loads((proposal / "wearable_assessments.json").read_text())
    guards = json.loads((proposal / "wearable_preservation_guards.json").read_text())
    probes = set()
    for row in targets:
        for field in row["held_fields"]:
            probes.add((field["section"], field["classname"], tuple(field["path"])))
    for row in guards:
        if not row["present"]:
            probes.add((row["section"], row["classname"], tuple(row["path"])))
    legacy = [r for r in assessments if r["status"] == "review_uniform_item_fields"]
    unresolved = [r for r in assessments if r["status"] == "unresolved_uniform_unit"]
    for row in legacy + unresolved:
        probes.add(("CfgWeapons", row["classname"], ("ItemInfo",)))
        if row.get("unit_class"):
            for field in ["armor", "armorStructural", "explosionShielding", "HitPoints"]:
                probes.add(("CfgVehicles", row["unit_class"], (field,)))
    probes = [[section, name, list(path)] for section, name, path in sorted(probes)]
    # An optional helmet pilot (build_helmet_pilot.py) can ride along in the full capture.
    pilot_root = root / "helmet-pilot"
    pilot, pilot_manifest = "", {"build_id": None, "verification_script_sha256": None}
    if (pilot_root / "manifest.json").exists():
        pilot_manifest = json.loads((pilot_root / "manifest.json").read_text())
        pilot_bytes = (pilot_root / "verify_helmet_pilot.sqf").read_bytes()
        if hashlib.sha256(pilot_bytes).hexdigest() != pilot_manifest["verification_script_sha256"]:
            raise ValueError("Pilot verifier does not match its manifest")
        pilot = pilot_bytes.decode("utf-8")
        if not pilot.startswith("[] spawn {") or not pilot.endswith("};\n"):
            raise ValueError("Unexpected pilot verifier wrapper")
        # Preserve the existing A3BALPILOT frames/importer, and await completion before
        # starting the supplemental phases. Store only a tiny completion summary.
        pilot = pilot.replace("[] spawn {", "private _pilotHandle = [] spawn {", 1)
        pilot = pilot[:-3] + '\n    missionNamespace setVariable ["A3BAL_batch_pilot_result", [count _checks, _checkedFields, _failed, _run]];\n};\n'
        pilot = ('missionNamespace setVariable ["A3BAL_batch_pilot_result", ["missing_or_aborted"]];\n'
                 + pilot + '\nwaitUntil {sleep 0.1; scriptDone _pilotHandle};\n'
                 '_pilot = missionNamespace getVariable ["A3BAL_batch_pilot_result", ["missing_or_aborted"]];')
    template = (root / "capture_remaining.template.sqf").read_text()
    identity = {"version": 1, "weapon_fields": WEAPON_FIELDS, "vehicle_fields": VEHICLE_FIELDS,
                "probes": probes, "pilot_build_id": pilot_manifest["build_id"],
                "template_sha256": hashlib.sha256(template.encode()).hexdigest(),
                "pilot_script_sha256": pilot_manifest["verification_script_sha256"]}
    suite_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    destination = root / "validation/remaining"
    destination.mkdir(parents=True, exist_ok=True)
    scripts = {}
    for mode in ("full", "clean"):
        script = template.replace("__MODE__", mode).replace("__SUITE_ID__", suite_id)
        script = script.replace("__WEAPON_FIELDS__", sqf(WEAPON_FIELDS)).replace("__VEHICLE_FIELDS__", sqf(VEHICLE_FIELDS))
        script = script.replace("__PROBES__", sqf(probes if mode == "full" else []))
        script = script.replace("__PILOT_BLOCK__", pilot if mode == "full" else "")
        if len(script.encode()) >= 9_000_000:
            raise ValueError("Batch exceeds safe clipboard size")
        path = destination / f"capture_{mode}.sqf"
        path.write_text(script, encoding="utf-8", newline="")
        scripts[mode] = {"file": path.name, "bytes": path.stat().st_size,
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = {**identity, "suite_id": suite_id, "scripts": scripts,
                "legacy_uniform_items": [r["classname"] for r in legacy],
                "unresolved_uniform_items": [r["classname"] for r in unresolved],
                "status": "Prepared; requires in-game execution. No held changes applied."}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"suite_id": suite_id, "probes": len(probes), "legacy_uniform_items": len(legacy), "scripts": scripts}


if __name__ == "__main__":
    print(json.dumps(prepare(Path(__file__).resolve().parent), indent=2))
