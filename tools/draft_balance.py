"""Draft a traceable vanilla-based balancing proposal from the recovered snapshot."""
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

from extract_rpt import canonical, get
from ammunition_policy import FAMILIES, build_ammunition_policy
from handheld_usage import classify
from wearable_assessment import build_assessments
from wearable_targets import build_wearable_targets, constant, preservation_guards


ARMOR_ANCHORS = [
    ("headgear", "ordinary_composite", "H_HelmetB"),
    ("headgear", "ordinary_composite", "H_HelmetIA"),
    ("headgear", "light_vanilla", "H_HelmetB_light"),
    ("headgear", "enhanced_vanilla", "H_HelmetSpecB"),
    ("headgear", "special_vanilla", "H_HelmetO_ocamo"),
    ("headgear", "crew_vanilla", "H_HelmetCrew_I"),
    ("headgear", "ceiling_vanilla", "H_HelmetLeaderO_ocamo"),
    ("headgear", "heli_aircrew_vanilla", "H_PilotHelmetHeli_B"),
    ("headgear", "heli_aircrew_vanilla", "H_CrewHelmetHeli_B"),
    ("headgear", "jet_pilot_vanilla", "H_PilotHelmetFighter_B"),
    ("headgear", "racing_vanilla", "H_RacingHelmet_1_F"),
    ("headgear", "hard_hat_vanilla", "H_Construction_basic_yellow_F"),
    ("vest", "load_bearing_only", "V_Chestrig_khk"),
    ("vest", "load_bearing_only", "V_BandollierB_khk"),
    ("vest", "soft_armor", "V_TacVest_khk"),
    ("vest", "flak_soft_armor", "V_TacVest_blk_POLICE"),
    ("vest", "light_rifle", "V_PlateCarrier1_rgr"),
    ("vest", "rifle", "V_PlateCarrier2_rgr"),
    ("vest", "heavy_rifle", "V_PlateCarrierSpec_rgr"),
    ("vest", "explosive_specialist_exception", "V_PlateCarrierGL_rgr"),
]
AMMO_ANCHORS = [(label, "generic_ball", vanilla) for _, label, vanilla, _ in FAMILIES]
MODERN_ANCHORS = [entry[2] for entry in ARMOR_ANCHORS if entry[1] == "ordinary_composite"]
# v8 adds the Serbian M97 (and LDF HB97/UHB13 reskins), 6B26/6B28, the Sfera/STSh-81 and 3CB ballistic masks.
MODERN = re.compile(r"(?<![a-z0-9])(?:ach|mich(?:[ -]?200[012])?|pasgt|fast|ops[ -]?core|6b47|6b27m?|lwh|6b7(?:[ -]?1m)?|mk[ -]?[67]|m97|hb97|uhb13|6b26|6b28|stsh[ -]?81|sfera|ballistic[ -]mask)(?![a-z0-9])", re.I)
# 1950s-era and WWII construction names are steel shells (v7 identification).
STEEL = re.compile(r"(?<![a-z0-9])(?:m[ -]?1[ch]?|ssh[ -]?(?:60|68)|m40|m42|m51|m53|m56|m59(?:/85)?|vz[ -]?53|mk[ -]?(?:ii|iii|iv)|hsat)(?![a-z0-9])", re.I)
CREW = re.compile(r"(?<![a-z0-9])(?:a?cvc(?:[ -]?h)?|6b48)(?![a-z0-9])|crew helmet", re.I)
AVIATION = re.compile(r"heli|pilot|aviat", re.I)
HELI_AIRCREW = re.compile(r"(?<![a-z0-9])(?:hgu[ -]?56(?:/p)?|sph[ -]?4[a-z]?|ihadss)(?![a-z0-9])|heli(?:copter)?[ -]?(?:pilot|crew)[ -]?helmet|pilothelmetheli|crewhelmetheli", re.I)
JET_PILOT = re.compile(r"(?<![a-z0-9])(?:zsh[ -]?7[a-z]?|hgu[ -]?55(?:/p)?)(?![a-z0-9])|jet[ -]?pilot|pilothelmetfighter", re.I)
HEAVY = re.compile(r"(?<![a-z0-9])(?:altyn|maska)(?![a-z0-9])", re.I)
RACING = re.compile(r"motorbike|motorcycle|racing[ -]?helmet", re.I)
# Pro-Tec shells are non-ballistic sport helmets, like a hard hat.
HARD_HAT = re.compile(r"(?<![a-z0-9])pro[ -]tec(?![a-z0-9])|hard[ -]?hat", re.I)
# "helmet cover" is a cloth item; "Helmet Covered" is a helmet wearing one.
EXCLUDED = re.compile(r"(?<![a-z0-9])(?:bump|airsoft|replica|liner|beret|boonie|cap|eod|dev|admin|uparmou?red|enhanced|heavy)(?![a-z0-9])|face[ -]?shield|neck protection|helmet cover(?!ed)", re.I)
# Each rule is a rung of the vanilla helmet ladder: (armor, passThrough, anchors).
HELMET_TIERS = {
    "derived_steel_light_vanilla": (4, .5, ["H_HelmetB_light"]),
    "ordinary_composite": (6, .5, MODERN_ANCHORS),
    "vanilla_crew_helmet": (8, .5, ["H_HelmetCrew_I"]),
    "vanilla_heavy_visored": (10, .5, ["H_HelmetSpecB"]),
    "vanilla_heli_aircrew": (6, .5, ["H_PilotHelmetHeli_B", "H_CrewHelmetHeli_B"]),
    "vanilla_jet_pilot": (8, .5, ["H_PilotHelmetFighter_B"]),
    "vanilla_racing_helmet": (4, .5, ["H_RacingHelmet_1_F"]),
    "vanilla_hard_hat": (2, .5, ["H_Construction_basic_yellow_F"]),
}
HELMET_REASONS = {
    "derived_steel_light_vanilla": "User-selected derived steel gameplay tier anchored to vanilla light helmet; not observed vanilla steel data.",
    "ordinary_composite": "Normalize the identified helmet family; preserve other covered regions, mass, and capacity.",
    "vanilla_crew_helmet": "Ground-vehicle crew helmet uses the vanilla crew helmet rung; aviation helmets are not included.",
    "vanilla_heavy_visored": "Heavy visored helmet uses the vanilla Enhanced Combat Helmet rung.",
    "vanilla_heli_aircrew": "Helicopter aircrew helmet uses the vanilla heli pilot/crew helmet values.",
    "vanilla_jet_pilot": "Fixed-wing pilot helmet uses the vanilla jet pilot helmet values.",
    "vanilla_racing_helmet": "Civilian motorcycle/racing helmet uses the vanilla racing helmet values.",
    "vanilla_hard_hat": "Non-ballistic hard shell uses the vanilla hard hat values.",
    "vanilla_model_twin": "Same 3D model as a vanilla helmet; use that vanilla helmet's values.",
}
# Unidentified gear may not exceed the top vanilla rung for its kind.
HELMET_CEILING = (12, .5, "H_HelmetLeaderO_ocamo")
AMMO_FIELDS = ["hit", "caliber", "typicalSpeed"]


def key_of(mapping, name):
    return next((key for key in mapping if key.lower() == name.lower()), None)


def head_entry(info):
    hp_key = key_of(info, "HitpointsProtectionInfo")
    if hp_key is None:
        return None
    matches = [(name, value) for name, value in info[hp_key].items()
               if isinstance(value, dict) and str(get(value, "hitpointName", "")).lower() == "hithead"]
    return (hp_key, *matches[0]) if len(matches) == 1 else None


def model_of(row):
    model = get(get(row["properties"], "ItemInfo", {}), "uniformModel", "") or ""
    return model.lower().replace("/", "\\").strip("\\").removesuffix(".p3d")


def model_twins(gear):
    """Vanilla helmet models whose loaded vanilla classes all share one armored head profile."""
    profiles = {}
    for row in gear:
        if row["kind"] != "headgear" or not is_reference(row) or not model_of(row):
            continue
        entry = head_entry(get(row["properties"], "ItemInfo", {}))
        values = entry and (constant(get(entry[2], "armor")), constant(get(entry[2], "passThrough")))
        profiles.setdefault(model_of(row), []).append((values, row["classname"]))
    return {model: (*rows[0][0], sorted(name for _, name in rows)[:3]) for model, rows in profiles.items()
            if len({values for values, _ in rows}) == 1 and rows[0][0] and None not in rows[0][0] and rows[0][0][0] > 0}


def helmet_rule(row, twins=None):
    info = get(row["properties"], "ItemInfo", {})
    name = row["classname"] + " " + str(get(row["properties"], "displayName", ""))
    if EXCLUDED.search(name):
        return None
    entry = head_entry(info)
    if entry is None:
        return None
    armor = constant(get(entry[2], "armor"))
    if armor is None or armor <= 0:
        return None
    if twins and model_of(row) in twins:
        return ("vanilla_model_twin", *twins[model_of(row)])
    if CREW.search(name) and not AVIATION.search(name):
        rule = "vanilla_crew_helmet"
    elif HELI_AIRCREW.search(name):
        rule = "vanilla_heli_aircrew"
    elif JET_PILOT.search(name):
        rule = "vanilla_jet_pilot"
    elif HEAVY.search(name):
        rule = "vanilla_heavy_visored"
    elif STEEL.search(name):
        rule = "derived_steel_light_vanilla"
    elif MODERN.search(name):
        rule = "ordinary_composite"
    elif RACING.search(name):
        rule = "vanilla_racing_helmet"
    elif HARD_HAT.search(name):
        rule = "vanilla_hard_hat"
    else:
        return None
    return (rule, *HELMET_TIERS[rule])


def ceiling_cap(row):
    """Armor/passThrough edits that bring unidentified head protection under the ladder top."""
    info = get(row["properties"], "ItemInfo", {})
    entry = head_entry(info)
    if entry is None:
        return []
    armor_key, through_key = key_of(entry[2], "armor"), key_of(entry[2], "passThrough")
    armor = constant(entry[2].get(armor_key))
    if armor is None or armor <= HELMET_CEILING[0]:
        return []
    edits = [(armor_key, armor, HELMET_CEILING[0])]
    through = constant(entry[2].get(through_key))
    if through is not None and through < HELMET_CEILING[1]:
        edits.append((through_key, through, HELMET_CEILING[1]))
    return [([key_of(row["properties"], "ItemInfo"), entry[0], entry[1], key], old, new) for key, old, new in edits]


def armor_values(row):
    info = get(row["properties"], "ItemInfo", {})
    return {name: {key: value for key, value in hp.items() if key != "$parent"}
            for name, hp in get(info, "HitpointsProtectionInfo", {}).items() if isinstance(hp, dict)}


def is_reference(row):
    name = row["classname"].lower()
    addons = [name.lower() for name in row["sourceAddons"]]
    return name.startswith(("h_", "v_", "u_", "g_", "b_")) and any(name.startswith("a3_") for name in addons)


def make_proposal(gear, ammo, usage=None):
    lookup = {row["classname"].lower(): row for row in gear + ammo}
    required = [row[2] for row in ARMOR_ANCHORS + AMMO_ANCHORS]
    absent = [name for name in required if name.lower() not in lookup]
    if absent:
        raise ValueError(f"Missing anchors: {absent}")
    def check_anchor(name, armor, through):
        anchor = lookup.get(name.lower())
        entry = head_entry(get(anchor["properties"], "ItemInfo", {})) if anchor else None
        if entry is None or (get(entry[2], "armor"), get(entry[2], "passThrough")) != (armor, through):
            raise ValueError(f"Vanilla reference changed: {name}")

    for name in MODERN_ANCHORS:
        check_anchor(name, 6, .5)
    twins = model_twins(gear)
    used = {rule[0] for row in gear if row["kind"] == "headgear" and not is_reference(row) and (rule := helmet_rule(row, twins))}
    for rule in sorted(used - {"ordinary_composite", "vanilla_model_twin"}):
        armor, through, names = HELMET_TIERS[rule]
        for name in names:
            check_anchor(name, armor, through)
    ceiling = HELMET_CEILING[2].lower() in lookup
    if ceiling:
        check_anchor(HELMET_CEILING[2], *HELMET_CEILING[:2])
    anchors = []
    for kind, role, name in ARMOR_ANCHORS:
        row = lookup[name.lower()]
        anchors.append({"section": "CfgWeapons", "kind": kind, "role": role,
                        "classname": row["classname"], "displayName": get(row["properties"], "displayName"),
                        "sourceAddons": row["sourceAddons"], "mass": get(get(row["properties"], "ItemInfo", {}), "mass"),
                        "protection": armor_values(row)})
    for cartridge, role, name in AMMO_ANCHORS:
        row = lookup[name.lower()]
        anchors.append({"section": "CfgAmmo", "kind": "projectile", "role": role,
                        "cartridge": cartridge, "classname": row["classname"],
                        "sourceAddons": row["sourceAddons"],
                        "values": {field: get(row["properties"], field) for field in AMMO_FIELDS + ["airFriction"]}})
    coverage, changes = [], []
    for row in gear:
        props = row["properties"]
        status, reason = "review_identity", "Equipment role has not been mapped to a reference."
        rule = None
        if is_reference(row):
            status, reason = "reference_preserved", "Loaded vanilla reference class; preserve the normalization baseline."
        elif row["kind"] == "headgear" and (rule := helmet_rule(row, twins)):
            status, reason = "matches_target", "Named helmet family matches the selected reference role."
            info_key = key_of(props, "ItemInfo")
            hp_key, region, values = head_entry(props[info_key])
            pending = []
            for field, target in (("armor", rule[1]), ("passThrough", rule[2])):
                field_key = key_of(values, field)
                old = constant(values.get(field_key))
                if old is None:
                    status, reason = "review_text_or_missing", "Protection field requires interpretation before assigning a target."
                    pending = []
                    break
                if old != target:
                    text = {} if isinstance(values.get(field_key), (int, float)) else {"old_text": values.get(field_key)}
                    pending.append({"section": "CfgWeapons", "classname": row["classname"], "kind": "headgear",
                                    "path": [info_key, hp_key, region, field_key], "old": old, **text, "proposed": target,
                                    "rule": rule[0], "anchors": rule[3], "confidence": "derived_vanilla_gameplay_rule" if rule[0] == "derived_steel_light_vanilla" else "vanilla_model_twin" if rule[0] == "vanilla_model_twin" else "named_family_proposal",
                                    "reason": HELMET_REASONS[rule[0]], "sourceAddons": row["sourceAddons"]})
            if pending:
                if get(props, "scope") == 2:
                    changes.extend(pending)
                    status = "proposed_change"
                else:
                    status, reason = "review_nonpublic_class", "Hidden/nonpublic class; assess inheritance and loadout usage before patching."
        elif row["kind"] == "headgear" and STEEL.search(row["classname"] + " " + str(get(props, "displayName", ""))):
            status, reason = "review_no_vanilla_equivalent", "Steel identity is recognized but its protection fields or exclusions prevent the derived tier from being assigned."
        elif row["kind"] == "headgear" and ceiling and get(props, "scope") == 2 and (capped := ceiling_cap(row)):
            status, reason = "proposed_ceiling_cap", "Unidentified headgear above the top vanilla rung is capped to it; identification may still assign a lower rung."
            rule = ("vanilla_ceiling_cap",)
            changes.extend({"section": "CfgWeapons", "classname": row["classname"], "kind": "headgear", "path": path,
                            "old": old, "proposed": new, "rule": "vanilla_ceiling_cap", "anchors": [HELMET_CEILING[2]],
                            "confidence": "ceiling_guard_unidentified",
                            "reason": "No identified rung; never exceed the strongest vanilla helmet.", "sourceAddons": row["sourceAddons"]}
                           for path, old, new in capped)
        elif row["kind"] == "glasses":
            status, reason = "preserved_no_target", "No glasses protection adjustment proposed."
        elif row["kind"] == "uniform":
            status, reason = "review_linked_unit", "Assess linked unit protection; avoid shared unit overrides in the first proposal."
        coverage.append({"section": "CfgWeapons" if row["kind"] != "glasses" else "CfgGlasses",
                         "classname": row["classname"], "kind": row["kind"], "scope": get(props, "scope"),
                         "status": status, "rule": rule[0] if rule else "", "reason": reason})
    ammunition = build_ammunition_policy(ammo, usage=usage)
    changes.extend(ammunition["changes"])
    existing = {row["classname"].lower() for row in anchors}
    for row in ammunition["mapping"]:
        coverage.append({"section": "CfgAmmo", "classname": row["classname"], "kind": "projectile", "scope": "",
                         "status": row["status"], "rule": "" if row["basis"] == "unassigned" else
                             "derived_specialized_ladder" if row["basis"] == "derived_specialized_ladder" else "vanilla_rifle_terminal_scale",
                         "reason": row["reason"]})
        name = row["reference_class"]
        if name and name.lower() not in existing:
            source = lookup[name.lower()]
            anchors.append({"section": "CfgAmmo", "kind": "projectile", "role": row["role"],
                            "cartridge": row["cartridge"], "classname": name, "sourceAddons": source["sourceAddons"],
                            "values": {field: get(source["properties"], field) for field in AMMO_FIELDS + ["airFriction"]}})
            existing.add(name.lower())
    return anchors, coverage, changes


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: canonical(row[key]) if isinstance(row.get(key), (dict, list)) else row.get(key, "")
                             for key in fields})


def inheritance_impacts(rows, changes, magazine_links):
    proposed = {(row["section"], row["classname"].lower()) for row in changes}
    inheritance = {key: [] for key in proposed}
    for row in rows:
        child_key = row["section"], row["classname"].lower()
        for parent in row["ancestry"][1:]:
            parent_key = row["section"], parent.lower()
            if parent_key in inheritance:
                inheritance[parent_key].append({"classname": row["classname"], "alsoProposed": child_key in proposed})
    impacts = []
    for section, name in sorted(proposed):
        descendants = inheritance[(section, name)]
        linked = {projectile: magazine_links.get(projectile.lower(), [])
                  for projectile in [name] + [row["classname"] for row in descendants]} if section == "CfgAmmo" else {}
        impacts.append({"section": section, "classname": name, "potentialDescendants": descendants,
                        "referencingMagazines": linked,
                        "note": "Class ancestry indicates possible propagation; ownership of individual inherited properties was not exported."})
    return impacts


# Full-preset batch capture (import_remaining_capture.py); without it, ammo usage is unproven and stays held.
USAGE_SNAPSHOT = Path(__file__).with_name("validation") / "remaining" / "full" / "snapshot.sqlite"


def draft(directory, output, usage_snapshot=USAGE_SNAPSHOT):
    with (directory / "wearables.jsonl").open(encoding="utf-8") as stream:
        gear = [json.loads(line) for line in stream]
    ammo, all_ammo, magazine_details, vehicles = [], [], [], []
    magazine_links = {}
    with (directory / "configs.relevant.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["section"] == "CfgAmmo":
                all_ammo.append(row)
                if get(row["properties"], "simulation") == "shotBullet":
                    ammo.append(row)
            elif row["section"] == "CfgVehicles":
                vehicles.append(row)
            elif row["section"] == "CfgMagazines":
                projectile = get(row["properties"], "ammo", "")
                if projectile:
                    magazine_links.setdefault(projectile.lower(), []).append(row["classname"])
                    magazine_details.append({"projectile": projectile, "magazine": row["classname"],
                                             "displayName": get(row["properties"], "displayName"),
                                             "rounds": get(row["properties"], "count"),
                                             "initSpeed": get(row["properties"], "initSpeed")})
    usage, usage_report = None, {"snapshot": None, "verdicts": {}}
    if usage_snapshot and Path(usage_snapshot).exists():
        usage = classify(usage_snapshot, [row["classname"] for row in ammo])
        with Path(usage_snapshot).open("rb") as stream:
            usage_report = {"snapshot": str(Path(usage_snapshot).relative_to(Path(__file__).parent)) if Path(usage_snapshot).is_relative_to(Path(__file__).parent) else str(usage_snapshot),
                            "sha256": hashlib.file_digest(stream, "sha256").hexdigest(),
                            "verdicts": dict(Counter(row["verdict"] for row in usage.values()))}
    anchors, coverage, changes = make_proposal(gear, ammo, usage)
    ammunition = build_ammunition_policy(all_ammo, usage=usage)
    assessment = build_assessments(gear, vehicles)
    wearable_plan = build_wearable_targets(gear, vehicles, assessment)
    changes.extend(wearable_plan["changes"])
    guards = preservation_guards(gear + vehicles, wearable_plan["changes"])
    helmet_guards = preservation_guards(gear, [row for row in changes if row["kind"] == "headgear"])
    assessed = {row["classname"].lower(): row for row in wearable_plan["targets"]}
    existing = {row["classname"].lower() for row in anchors}
    gear_lookup = {row["classname"].lower(): row for row in gear}
    unit_lookup = {row["classname"].lower(): row for row in vehicles}
    for name in wearable_plan["used_anchors"]:
        if name.lower() not in existing:
            row = gear_lookup[name.lower()]
            anchor = {"section": "CfgWeapons", "kind": row["kind"], "role": "vanilla_wearable_target",
                      "classname": name, "displayName": get(row["properties"], "displayName"),
                      "sourceAddons": row["sourceAddons"], "protection": armor_values(row)}
            if row["kind"] == "uniform":
                unit = unit_lookup[get(get(row["properties"], "ItemInfo", {}), "uniformClass").lower()]
                anchor.update(unitClass=unit["classname"], unitProtection=get(unit["properties"], "HitPoints", {}),
                              unitValues={field: get(unit["properties"], field) for field in ("armor", "armorStructural", "explosionShielding")})
            anchors.append(anchor)
            existing.add(name.lower())
    for row in coverage:
        if row["kind"] in {"vest", "uniform"}:
            item = assessed[row["classname"].lower()]
            row.update(status=item["status"], rule="vanilla_wearable_target", reason=item["reason"])
    impacts = inheritance_impacts(gear + all_ammo + vehicles, changes, magazine_links)
    extraction = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    hashes = {}
    for name in ("wearables.jsonl", "configs.relevant.jsonl"):
        with (directory / name).open("rb") as stream:
            hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {"proposal_version": 11, "baseline": "loaded_vanilla_only", "source_run": extraction["run"], "source_status": extraction["status"],
              "source_missing_by_section": extraction["missing_by_section"],
              "source_sha256": hashes,
              "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "ammunition_generator_sha256": hashlib.sha256(Path(__file__).with_name("ammunition_policy.py").read_bytes()).hexdigest(),
              "wearable_assessment_generator_sha256": hashlib.sha256(Path(__file__).with_name("wearable_assessment.py").read_bytes()).hexdigest(),
              "wearable_assessment": assessment["summary"],
              "wearable_targets_generator_sha256": hashlib.sha256(Path(__file__).with_name("wearable_targets.py").read_bytes()).hexdigest(),
              "wearable_targets": wearable_plan["summary"],
              "handheld_usage_generator_sha256": hashlib.sha256(Path(__file__).with_name("handheld_usage.py").read_bytes()).hexdigest(),
              "handheld_usage": usage_report,
              "ammunition_cartridges": ammunition["cartridges"],
              "release_stage": "v11 ladder draft; helmet pilot v9 verified in game; range test done (Tigr hull loss accepted); S&S true-text passThrough written as vanilla 1; combined pilot (helmets, vests, uniform units, ammunition) with one-session check built and awaiting in-game verification; civilian global fields (measured in the session) and legacy uniform items held",
              "helmet_preservation_guard_rows": len(helmet_guards),
              "wearable_target_rows": len(wearable_plan["targets"]),
              "wearable_preservation_guard_rows": len(guards),
              "wearable_preservation_statuses": dict(Counter(row["status"] for row in guards)),
              "anchors": len(anchors), "coverage_rows": len(coverage),
              "coverage_statuses": dict(Counter(row["status"] for row in coverage)),
              "proposed_classes": dict(Counter(kind for kind, _ in {(row["kind"], row["classname"]) for row in changes})),
              "proposed_field_changes": len(changes),
              "ammunition_penetration_check_rows": len(ammunition["penetration_checks"]),
              "ammunition_mapping_rows": len(ammunition["mapping"]), "ammunition_families": len(ammunition["families"]),
              "ammunition_preservation_guards": len(ammunition["preservation_guards"]),
              "ammunition_policy": ammunition["summary"],
              "potential_unproposed_descendants": len({(row["section"], child["classname"].lower())
                  for row in impacts for child in row["potentialDescendants"] if not child["alsoProposed"]}),
              "rule_class_counts": dict(Counter(rule for rule, _ in {(row["rule"], row["classname"]) for row in changes})),
              "stage": "draft ledger; no generated or installed patch"}
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (("anchors", anchors), ("change_ledger", changes), ("inheritance_review", impacts),
                        ("ammunition_mapping", ammunition["mapping"]), ("ammunition_families", ammunition["families"]),
                        ("ammunition_preservation_guards", ammunition["preservation_guards"]),
                        ("wearable_assessments", assessment["assessments"]),
                        ("wearable_comparisons", assessment["comparisons"]),
                        ("uniform_unit_usage", assessment["unit_usage"]),
                        ("wearable_targets", wearable_plan["targets"]),
                        ("wearable_preservation_guards", guards),
                        ("helmet_preservation_guards", helmet_guards),
                        ("ammunition_penetration_checks", ammunition["penetration_checks"]),
                        ("ammunition_handheld_usage", sorted((usage or {}).values(), key=lambda row: row["classname"].lower())),
                        ("summary", report)):
        (output / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(output / "helmet_preservation_guards.csv", helmet_guards,
              ["section", "classname", "path", "present", "retain", "changed_ancestors", "status"])
    write_csv(output / "ammunition_penetration_checks.csv", ammunition["penetration_checks"],
              ["classname", "cartridge", "role", "observed_penetration", "candidate_ball_penetration", "ladder_penetration",
               "expectation", "status", "ladder_status"])
    write_csv(output / "wearable_targets.csv", wearable_plan["targets"],
              ["classname", "kind", "role", "status", "reference_class", "patch_section", "patch_class", "field_changes", "held_fields", "notes", "reason"])
    write_csv(output / "wearable_preservation_guards.csv", guards,
              ["section", "classname", "path", "present", "retain", "changed_ancestors", "status"])
    write_csv(output / "wearable_assessments.csv", assessment["assessments"],
              ["classname", "kind", "role", "status", "basis", "profile_id", "candidate_references", "matching_references",
               "flags", "unit_class", "shared_uniform_count", "unit_descendant_count", "declared_wearer_count", "reason"])
    write_csv(output / "wearable_comparisons.csv", assessment["comparisons"],
              ["classname", "reference_class", "path", "current_present", "reference_present", "current", "reference"])
    write_csv(output / "coverage.csv", coverage, ["section", "classname", "kind", "scope", "status", "rule", "reason"])
    write_csv(output / "change_ledger.csv", changes,
              ["section", "classname", "kind", "path", "old", "proposed", "rule", "anchors", "confidence", "reason", "sourceAddons"])
    mapping_rows = [{**row, **{f"current_{key}": value for key, value in row["current"].items()},
                    **{f"proposed_{key}": value for key, value in (row["proposed"] or {}).items()}}
                   for row in ammunition["mapping"]]
    write_csv(output / "ammunition_mapping.csv", mapping_rows,
              ["classname", "cartridge", "role", "ladder_role", "tracer_name_flag", "status", "basis", "reference_class", "reference_ball",
               "hit_multiplier", "usage_verdict", "current_hit", "current_caliber", "current_typicalSpeed",
               "proposed_hit", "proposed_caliber", "proposed_typicalSpeed", "candidate", "reason"])
    write_csv(output / "ammunition_families.csv", ammunition["families"],
              ["cartridge", "vanilla_anchor", "rhs_anchor", "vanilla_coefficient", "rhs_coefficient", "hit_multiplier",
               "target_hit", "target_caliber", "target_typical_speed", "assumption"])
    write_csv(output / "ammunition_magazine_uses.csv", magazine_details,
              ["projectile", "magazine", "displayName", "rounds", "initSpeed"])
    anchor_rows = []
    for anchor in anchors:
        if anchor["section"] == "CfgAmmo":
            anchor_rows.append({**anchor, **anchor["values"]})
        else:
            protection = anchor.get("unitProtection", anchor["protection"])
            if not protection:
                anchor_rows.append(anchor)
            for region, values in protection.items():
                if not isinstance(values, dict):
                    continue
                anchor_rows.append({**anchor, "region": region, "armor": get(values, "armor"),
                                    "passThrough": get(values, "passThrough")})
    write_csv(output / "anchors.csv", anchor_rows,
              ["section", "kind", "role", "cartridge", "classname", "displayName", "mass", "region", "armor",
               "passThrough", "hit", "caliber", "typicalSpeed", "airFriction", "sourceAddons"])
    return report


if __name__ == "__main__":
    print(json.dumps(draft(Path(sys.argv[1]), Path(sys.argv[2]), *(Path(arg) for arg in sys.argv[3:4])), indent=2))
