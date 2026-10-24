"""Explicit vanilla gameplay targets; raw exports and scripted systems stay untouched."""
from collections import Counter, defaultdict
import ast
import math
import operator
import re

from extract_rpt import get


def numeric(value):
    return type(value) in (int, float) and math.isfinite(value)


CONSTANT_TEXT = re.compile(r"[\d.\s+\-*/()]+")
OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
BOOLEAN_TEXT = {"true": 1, "false": 0}


def constant(value):
    """Number for a numeric value or a pure arithmetic literal such as "22+ 3" (the engine evaluates it); else None."""
    if numeric(value):
        return value
    if not isinstance(value, str) or not CONSTANT_TEXT.fullmatch(value):
        return None

    def evaluate(node):
        if isinstance(node, ast.Constant) and numeric(node.value):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -evaluate(node.operand)
        if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
            return OPERATORS[type(node.op)](evaluate(node.left), evaluate(node.right))
        raise ValueError

    try:
        result = evaluate(ast.parse(value.strip(), mode="eval").body)
    except (SyntaxError, ValueError, ZeroDivisionError):
        return None
    return result if numeric(result) else None


def key_of(value, name):
    return next((key for key in value if key.lower() == name.lower()), None)


def leaves(value, path=()):
    for key, child in value.items():
        if key == "$parent":
            continue
        if isinstance(child, dict):
            yield from leaves(child, path + (key,))
        else:
            yield path + (key,), child


def vanilla(row):
    return row["classname"].lower().startswith(("v_", "u_", "b_", "o_", "i_", "c_")) and any(
        addon.lower().startswith("a3_") for addon in row["sourceAddons"])


def regions(props):
    info_key = key_of(props, "ItemInfo")
    info = props.get(info_key, {})
    hp_key = key_of(info, "HitpointsProtectionInfo")
    hp = info.get(hp_key, {})
    result = {}
    for name, value in hp.items():
        if isinstance(value, dict):
            hit = str(get(value, "hitpointName", "")).lower()
            if not hit or hit in result:
                raise ValueError("Ambiguous vest hitpoint mapping")
            result[hit] = ([info_key, hp_key, name], value)
    return result


# Flak vests use vanilla's stronger soft rung (12/0.4); other soft vests use 8/0.5.
FLAK = re.compile(r"\b(?:pasgt|6b2|m1952|m1955|m1969|m69|m55)\b|\bflak\b")
# Soft armor with plate pockets (MBAV) and plates-only minimal carriers (Plateframe, MBSS)
# use the vanilla light carrier rung (16/0.3).
LIGHT_CARRIER = re.compile(r"\b(?:mbav|plateframe|mbss)\b")
# Heavy armor names that select the top ordinary vanilla rung.
HEAVY_ARMOR = re.compile(r"\b(?:iotv|iba|mtv|osprey|6b13|6b43|6b45)\b|heavy armou?r|\b6b armor\b")
# Unidentified vests may not exceed the top ordinary vanilla rung.
VEST_CEILING = ("V_PlateCarrierSpec_rgr", 24, .1)
NO_CEILING_ROLES = {"explosive_specialist", "diving"}


def vest_tier(row, role):
    text = re.sub(r"[_-]", " ", row["classname"] + " " + str(get(row["properties"], "displayName", ""))).lower()
    if role == "load_bearing":
        return "V_Chestrig_khk"
    if role == "soft_fragmentation":
        # Pilot vests are flak survival vests unless built on a plate armor base (Osprey: heavy plate).
        if "pilot" in text:
            lineage = re.sub(r"[_-]", " ", " ".join(row.get("ancestry", [])[1:])).lower()
            return "V_PlateCarrierSpec_rgr" if HEAVY_ARMOR.search(lineage) else "V_TacVest_blk_POLICE"
        return "V_TacVest_blk_POLICE" if FLAK.search(text) else "V_TacVest_khk"
    if role == "plate_carrier":
        return "V_PlateCarrier1_rgr" if LIGHT_CARRIER.search(text) else "V_PlateCarrier2_rgr"
    if role == "extended_armor":
        return "V_PlateCarrierSpec_rgr" if HEAVY_ARMOR.search(text) else "V_PlateCarrier2_rgr"
    return None


def ceiling_edits(row):
    """Cap numeric regional armor above the ceiling rung; never add or zero a field."""
    name, armor_cap, through_floor = VEST_CEILING
    edits = []
    for hit, (prefix, values) in regions(row["properties"]).items():
        armor_key, through_key = key_of(values, "armor"), key_of(values, "passThrough")
        armor = constant(values.get(armor_key))
        if armor is None or armor <= armor_cap:
            continue
        fields = [(armor_key, armor, armor_cap)]
        through = constant(values.get(through_key))
        if through is not None and through < through_floor:
            fields.append((through_key, through, through_floor))
        edits.extend({"section": "CfgWeapons", "classname": row["classname"], "kind": "vest",
                      "path": prefix + [key], "old": old, **({} if numeric(values[key]) else {"old_text": values[key]}),
                      "proposed": new, "rule": "vanilla_ceiling_cap",
                      "anchors": [name], "confidence": "ceiling_guard_unidentified",
                      "reason": "No identified tier; never exceed the strongest ordinary vanilla vest.",
                      "sourceAddons": row["sourceAddons"]} for key, old, new in fields)
    return edits


def build_wearable_targets(gear, vehicles, assessment):
    gear_lookup = {row["classname"].lower(): row for row in gear}
    unit_lookup = {row["classname"].lower(): row for row in vehicles}
    assessed = {row["classname"].lower(): row for row in assessment["assessments"]}
    unit_users = {row["unit_class"].lower(): row["uniforms"] for row in assessment["unit_usage"]}
    changes, targets, used_anchors = [], [], set()
    unit_plans = defaultdict(list)
    for item in assessment["assessments"]:
        row = gear_lookup[item["classname"].lower()]
        props = row["properties"]
        target = {"classname": row["classname"], "kind": row["kind"], "role": item["role"],
                  "status": item["status"], "reference_class": None, "patch_section": None,
                  "patch_class": None, "field_changes": 0, "held_fields": [], "notes": [],
                  "reason": item["reason"]}
        targets.append(target)
        if vanilla(row) or item["status"] in {"unresolved_uniform_unit", "matches_vanilla_profile"}:
            continue
        if get(props, "scope") != 2:
            target.update(status="review_nonpublic_class", reason="No direct target for hidden or textual-scope equipment; inheritance is reviewed separately.")
            continue
        pending = []

        def propose(section, source, path, old, desired, reference, rule):
            # Bare true/false text (S&S hitpoint passThrough) reads as 1/0; the vanilla number is written explicitly
            # even when equal, so the field ends at vanilla however the engine reads the text.
            boolean = isinstance(old, str) and old.strip().lower() in BOOLEAN_TEXT
            value = BOOLEAN_TEXT[old.strip().lower()] if boolean else constant(old)
            if section == "CfgVehicles" and item["role"] == "civilian_clothing" and len(path) == 1 and path[0].lower() in {"armorstructural", "explosionshielding"} and old != desired:
                target["held_fields"].append({"section": section, "classname": source["classname"], "path": path,
                                               "old": old, "candidate": desired, "reason": "civilian_globals_need_in_game_test"})
            elif value is None or not numeric(desired):
                target["held_fields"].append({"section": section, "classname": source["classname"], "path": path,
                                               "old": old, "candidate": desired, "reason": "Text or missing value requires engine verification."})
            elif value != desired or boolean:
                text = {} if numeric(old) else {"old_text": old}
                pending.append({"section": section, "classname": source["classname"],
                                "kind": "vest" if section == "CfgWeapons" else "uniform_unit",
                                "path": path, "old": value, **text, "proposed": desired, "rule": rule,
                                "anchors": [reference], "confidence": "explicit_vanilla_gameplay_tier",
                                "reason": "Normalize the selected gameplay role using vanilla; preserve geometry, coverage, mass, capacity and scripts.",
                                "sourceAddons": source["sourceAddons"]})

        if row["kind"] == "vest":
            reference = vest_tier(row, item["role"])
            if reference is None:
                target.update(status="review_no_selected_vest_tier", reason="Construction, specialist function or modular loadout needs a separate target decision.")
                capped = [] if item["role"] in NO_CEILING_ROLES else ceiling_edits(row)
                if capped:
                    changes.extend(capped)
                    used_anchors.add(VEST_CEILING[0])
                    target.update(status="proposed_ceiling_cap", reference_class=VEST_CEILING[0], patch_section="CfgWeapons",
                                  patch_class=row["classname"], field_changes=len(capped),
                                  reason="Unidentified vest above the strongest ordinary vanilla rung is capped to it; identification may still assign a lower tier.")
                continue
            anchor = gear_lookup[reference.lower()]
            if not vanilla(anchor):
                raise ValueError(f"Non-vanilla target anchor: {reference}")
            source_regions, anchor_regions = regions(props), regions(anchor["properties"])
            if not source_regions:
                target.update(status="review_missing_protection", reason="No existing vest region structure to normalize.")
                continue
            if item["role"] != "load_bearing" and any(
                    hit not in source_regions or get(source_regions[hit][1], "armor") is None or
                    (armor := constant(get(source_regions[hit][1], "armor"))) is not None and armor <= 0
                    for hit in ("hitchest", "hitdiaphragm")):
                target.update(status="review_plate_or_soft_identity", reason="Named armor has missing or nonpositive torso protection; no tier is forced onto it.")
                continue
            target.update(reference_class=reference, patch_section="CfgWeapons", patch_class=row["classname"])
            for hit, (prefix, values) in source_regions.items():
                if item["role"] == "load_bearing":
                    desired = {"armor": 0, "passThrough": 1}
                    target["notes"] = ["Apply the vanilla unarmored load-bearing state to existing regions only; no region is added."]
                elif hit in anchor_regions:
                    desired = anchor_regions[hit][1]
                    chest_armor = constant(get(source_regions.get("hitchest", ([], {}))[1], "armor"))
                    abdomen_armor = constant(get(values, "armor"))
                    if hit == "hitabdomen" and chest_armor is not None and abdomen_armor is not None and abdomen_armor < chest_armor:
                        target["notes"].append("Preserve weaker abdomen in a mixed protection profile; do not promote it to the torso plate tier.")
                        continue
                    # Low/absent abdominal protection on partial carriers is not a plate.
                    if hit == "hitabdomen" and item["role"] == "plate_carrier" and re.search(
                            r"\b(?:mbav|mbss|rrv|spcs?|plateframe|protec|lbt|6094)\b",
                            re.sub(r"[_-]", " ", row["classname"] + " " + str(get(props, "displayName", ""))), re.I):
                        target["notes"].append("Preserve partial-carrier abdomen; no verified vanilla counterpart for the secondary protection.")
                        continue
                    if hit != "hitbody" and constant(get(values, "armor")) == 0:
                        target["notes"].append(f"Preserve unarmored {hit}; no coverage expansion.")
                        continue
                else:
                    target["notes"].append(f"Preserve {hit}; selected vanilla tier does not define that region.")
                    continue
                for field in ("armor", "passThrough"):
                    key, reference_key = key_of(values, field), key_of(desired, field)
                    if key is not None and reference_key is not None:
                        propose("CfgWeapons", row, prefix + [key], values[key], desired[reference_key], reference, "vanilla_vest_role_tier")
                    elif key is not None and reference_key is None:
                        target["notes"].append(f"Preserve {hit}/{field}; vanilla has no corresponding field.")
            if any(key.lower() in {"armor", "passthrough"} for key in get(props, "ItemInfo", {})):
                target["notes"].append("Legacy item armor/passThrough has no selected vanilla counterpart and is retained.")
            changes.extend(pending)
        else:
            if "legacy_item_fields" in item["flags"]:
                target.update(status="review_uniform_item_fields", reason="Vanilla omits these legacy item fields; absent is not a justified numeric zero target.")
                continue
            if item["role"] not in {"ordinary_clothing", "civilian_clothing"}:
                target.update(status="review_specialized_uniform", reason="Specialized uniform profiles remain distinct; no ordinary-clothing fallback.")
                continue
            reference = "U_C_Poloshirt_blue" if item["role"] == "civilian_clothing" else "U_B_CombatUniform_mcam"
            reference_gear = gear_lookup[reference.lower()]
            unit_name = item["unit_class"]
            source = unit_lookup[unit_name.lower()]
            reference_unit = unit_lookup[get(get(reference_gear["properties"], "ItemInfo", {}), "uniformClass").lower()]
            if not vanilla(reference_gear) or not vanilla(reference_unit):
                raise ValueError(f"Non-vanilla uniform target: {reference}")
            if vanilla(source):
                target.update(status="reference_preserved", reason="Linked vanilla soldier class is part of the baseline.")
                continue
            target.update(reference_class=reference, patch_section="CfgVehicles", patch_class=source["classname"])
            ref_leaves = {tuple(key.lower() for key in path): value for path, value in leaves(reference_unit["properties"])}
            for path, old in leaves(source["properties"]):
                lower_path = tuple(key.lower() for key in path)
                allowed = lower_path in {(name,) for name in ("armor", "armorstructural", "explosionshielding", "damageresistance", "impactdamagemultiplier")} or (
                    len(path) == 3 and lower_path[0] == "hitpoints" and lower_path[-1] in {"armor", "passthrough", "explosionshielding"})
                if allowed and lower_path in ref_leaves:
                    propose("CfgVehicles", source, list(path), old, ref_leaves[lower_path], reference, "vanilla_uniform_body_tier")
            unit_plans[unit_name.lower()].append((target, pending))
            target["notes"].append("Unit overrides require descendant preservation; radius, selection names, dependencies and visuals are retained.")
        used_anchors.add(reference)
        target["field_changes"] = len(pending)
        target["status"] = "proposed_partial_wearable_change" if pending and (target["held_fields"] or target["notes"] and row["kind"] == "vest" and item["role"] != "load_bearing") else (
            "proposed_wearable_change" if pending else "review_held_target_fields" if target["held_fields"] else
            "selected_target_with_retained_fields" if target["notes"] and row["kind"] == "vest" else "matches_selected_target")
        target["reason"] = "Selected explicit vanilla gameplay tier; only listed numeric fields are proposed."
    target_lookup = {row["classname"].lower(): row for row in targets}
    for unit, plans in unit_plans.items():
        signatures = [{tuple(change["path"]): change["proposed"] for change in pending} for _, pending in plans]
        conflict = any(signature != signatures[0] for signature in signatures[1:])
        if any(target_lookup[name.lower()]["patch_class"] is None for name in unit_users[unit]):
            conflict = True
        if conflict:
            for target, _ in plans:
                target.update(status="review_shared_unit_target_conflict", field_changes=0,
                              reason="Referencing uniforms do not all support the same direct unit override; no change emitted.")
        else:
            # One unit field is emitted once even when several uniforms refer to it.
            changes.extend(plans[0][1])
    return {"targets": targets, "changes": changes, "used_anchors": sorted(used_anchors),
            "summary": {"statuses": dict(Counter(row["status"] for row in targets)),
                        "proposed_wearables": dict(Counter(row["kind"] for row in targets if row["field_changes"])),
                        "field_changes": len(changes), "changed_unit_classes": len({row["classname"] for row in changes if row["section"] == "CfgVehicles"}),
                        "held_text_fields": sum(isinstance(field["old"], str) for row in targets for field in row["held_fields"]),
                        "held_civilian_global_fields": sum(field["reason"] == "civilian_globals_need_in_game_test" for row in targets for field in row["held_fields"])}}


def preservation_guards(rows, changes):
    """Retain observed descendant fields unless that exact field has its own target."""
    changed = defaultdict(dict)
    for row in changes:
        changed[(row["section"], row["classname"].lower())][tuple(key.lower() for key in row["path"])] = row["proposed"]
    guards = []
    for row in rows:
        own_key = (row["section"], row["classname"].lower())
        inherited = {}
        ancestors = defaultdict(list)
        for parent in row["ancestry"][1:]:
            for path, target in changed.get((row["section"], parent.lower()), {}).items():
                inherited.setdefault(path, target)
                ancestors[path].append(parent)
        for path, target in inherited.items():
            if path in changed.get(own_key, {}):
                continue
            current, actual_path = row["properties"], []
            for part in path:
                key = key_of(current, part) if isinstance(current, dict) else None
                if key is None:
                    break
                actual_path.append(key)
                current = current[key]
            present = len(actual_path) == len(path)
            old = current if present else None
            if present and old == target:
                continue
            guards.append({"section": row["section"], "classname": row["classname"], "path": actual_path if present else list(path),
                           "present": present, "retain": old, "changed_ancestors": ancestors[path],
                           "status": "retain_observed_field" if present else "review_missing_descendant_path"})
    return guards
