"""Inventory protection profiles and review candidates without choosing balance values."""
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sys

from extract_rpt import canonical, get


def semantic(value):
    """Ignore config key casing and inheritance labels, preserving actual values."""
    if isinstance(value, dict):
        return {key.lower(): semantic(child) for key, child in value.items() if key != "$parent"}
    if isinstance(value, list):
        return [semantic(child) for child in value]
    return value


def select(props, fields):
    return {key.lower(): semantic(value) for key, value in props.items() if key.lower() in fields}


PROTECTION_FIELDS = {"armor", "passthrough", "explosionshielding", "hitpointname", "hitpointsprotectioninfo"}
UNIT_FIELDS = {"armor", "armorstructural", "explosionshielding", "damageresistance",
               "impactdamagemultiplier", "hitpoints"}
BULLET_FIELDS = set("""
    hit caliber typicalspeed airfriction waterfriction indirecthit indirecthitrange
    explosive deflecting deflectiondirfactor deflectionslowdown penetrationdirdeviation
    penetrationdirfactor penetrationslowdown submunitionammo submunitioncount
    ace_caliber ace_bulletmass ace_bulletlength ace_ballisticcoefficients
    ace_velocityboundaries ace_dragmodel ace_standardatmosphere ace_muzzlevelocities
    ace_barrellengths ace_muzzlevelocityvariationsd ace_ammotempmuzzlevelocityshifts
""".split())


def protection(row, units):
    props = row["properties"]
    info = props if row["kind"] == "glasses" else get(props, "ItemInfo", {})
    value = {"kind": row["kind"], "item": select(info, PROTECTION_FIELDS)}
    if row["kind"] == "uniform":
        reference = get(info, "uniformClass", "")
        unit = units.get(reference.lower())
        value["unit"] = select(unit, UNIT_FIELDS) if unit is not None else {"unresolved": reference}
    return value


def profile_id(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()[:20]


def numeric_findings(value, path=""):
    for key, child in value.items():
        current = f"{path}/{key}" if path else key
        if isinstance(child, dict):
            yield from numeric_findings(child, current)
        elif key in {"armor", "armorstructural", "passthrough", "explosionshielding"}:
            if isinstance(child, str):
                yield current, "numeric_field_stored_as_text", child
            elif isinstance(child, (int, float)):
                if key == "passthrough" and not 0 <= child <= 1:
                    yield current, "passThrough_outside_0_to_1", child
                elif child < 0:
                    yield current, "negative_protection_value", child


def build_report(gear, units, bullets):
    profiles = {}
    models = defaultdict(list)
    findings = []
    for row in gear:
        props = row["properties"]
        value = protection(row, units)
        key = profile_id(value)
        group = profiles.setdefault(key, {"id": key, "kind": row["kind"],
                                          "protection": value, "classes": []})
        group["classes"].append(row["classname"])
        for field, reason, raw in numeric_findings(value):
            findings.append({"classname": row["classname"], "kind": row["kind"],
                             "field": field, "reason": reason, "value": raw})
        scope = get(props, "scope")
        if isinstance(scope, str):
            findings.append({"classname": row["classname"], "kind": row["kind"],
                             "field": "scope", "reason": "scope_stored_as_text", "value": scope})
        info = get(props, "ItemInfo", {})
        model = get(info, "uniformModel", "")
        if row["kind"] in {"vest", "headgear"} and model and model != "-":
            models[(row["kind"], model.lower().replace("/", "\\").lstrip("\\").removesuffix(".p3d"))].append({
                "classname": row["classname"], "displayName": get(props, "displayName"),
                "scope": scope, "mass": get(info, "mass"), "profile": key,
                "sourceAddons": row["sourceAddons"]})
    candidates = []
    for (kind, model), members in models.items():
        distinct = {member["profile"] for member in members}
        public = [member for member in members if member["scope"] == 2]
        if len(distinct) > 1:
            candidates.append({"kind": kind, "model": model, "profileCount": len(distinct),
                               "publicProfileCount": len({member["profile"] for member in public}),
                               "publicVariantCount": len(public),
                               "members": members})
    candidates.sort(key=lambda row: (-row["profileCount"], -len(row["members"]), row["model"]))
    ammo_profiles = {}
    for row in bullets:
        value = select(row["properties"], BULLET_FIELDS)
        key = profile_id(value)
        group = ammo_profiles.setdefault(key, {"id": key, "properties": value, "classes": []})
        group["classes"].append(row["classname"])
    return {
        "summary": {
            "wearables": dict(Counter(row["kind"] for row in gear)),
            "protection_profiles": dict(Counter(row["kind"] for row in profiles.values())),
            "shared_models_with_differing_protection": dict(Counter(row["kind"] for row in candidates)),
            "shared_models_with_differing_public_protection": dict(Counter(
                row["kind"] for row in candidates if row["publicProfileCount"] > 1)),
            "unresolved_uniform_profiles": sum(
                "unresolved" in row["protection"].get("unit", {}) for row in profiles.values()),
            "finding_counts": dict(Counter(row["reason"] for row in findings)),
            "bullet_classes": len(bullets), "selected_bullet_profiles": len(ammo_profiles),
            "limits": ["Profiles compare exported fields, not measured damage outcomes.",
                       "Same model does not prove same armor construction or plate loadout.",
                       "Text arithmetic remains text; it is neither assumed zero nor declared invalid.",
                       "Missing unit links remain unresolved, never replaced by zero protection.",
                       "No baseline, real-world protection tier, or patch value has been assigned."]},
        "profiles": list(profiles.values()), "shared_models": candidates,
        "findings": findings, "bullet_profiles": list(ammo_profiles.values())}


def audit(directory, output):
    with (directory / "wearables.jsonl").open(encoding="utf-8") as stream:
        gear = [json.loads(line) for line in stream]
    references = {get(get(row["properties"], "ItemInfo", {}), "uniformClass", "").lower()
                  for row in gear if row["kind"] == "uniform"}
    units, bullets = {}, []
    with (directory / "configs.relevant.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["section"] == "CfgVehicles" and row["classname"].lower() in references:
                units[row["classname"].lower()] = row["properties"]
            elif row["section"] == "CfgAmmo" and get(row["properties"], "simulation") == "shotBullet":
                bullets.append(row)
    report = build_report(gear, units, bullets)
    output.mkdir(parents=True, exist_ok=True)
    for key in ("summary", "profiles", "shared_models", "bullet_profiles"):
        (output / f"{key}.json").write_text(json.dumps(report[key], ensure_ascii=False, indent=2), encoding="utf-8")
    with (output / "findings.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["classname", "kind", "field", "reason", "value"])
        writer.writeheader()
        writer.writerows(report["findings"])
    return report["summary"]


if __name__ == "__main__":
    print(json.dumps(audit(Path(sys.argv[1]), Path(sys.argv[2])), indent=2))
