"""Classify wearable roles and compare observations with loaded vanilla references."""
from collections import Counter, defaultdict
import re

from audit_configs import protection, profile_id
from extract_rpt import get


VEST_REFERENCES = {
    "load_bearing": ["V_Chestrig_khk", "V_BandollierB_khk", "V_HarnessO_brn", "V_Rangemaster_belt"],
    "soft_fragmentation": ["V_TacVest_khk", "V_TacVest_blk_POLICE", "V_Press_F"],
    "plate_carrier": ["V_PlateCarrier1_rgr", "V_PlateCarrier2_rgr"],
    "extended_armor": ["V_PlateCarrier2_rgr", "V_PlateCarrierSpec_rgr", "V_PlateCarrierIA2_dgtl"],
    "explosive_specialist": ["V_PlateCarrierGL_rgr", "V_EOD_blue_F"],
    "diving": ["V_RebreatherB"],
    "modular_carrier": ["V_CarrierRigKBT_01_EAF_F", "V_CarrierRigKBT_01_light_EAF_F",
                        "V_CarrierRigKBT_01_heavy_EAF_F"],
}
UNIFORM_REFERENCES = {
    "ordinary_clothing": ["U_B_CombatUniform_mcam", "U_I_CombatUniform"],
    "civilian_clothing": ["U_C_Poloshirt_blue"],
    "pilot_coveralls": ["U_B_PilotCoveralls", "U_I_pilotCoveralls", "U_I_E_Uniform_01_coveralls_F", "U_O_PilotCoveralls"],
    "diving": ["U_B_Wetsuit", "U_O_Wetsuit"],
    "cbrn": ["U_B_CBRN_Suit_01_MTP_F"],
    "integrated_armor": ["U_O_CombatUniform_ocamo"],
    "special_purpose": ["U_O_V_Soldier_Viper_F"],
    "virtual_reality": ["U_B_Protagonist_VR", "U_B_Soldier_VR"],
}
# Name rules describe gameplay construction, never a certification or a numeric tier.
VEST_RULES = [
    ("explosive_specialist", r"\beod\b|explosive|bomb suit|carrier gl rig"),
    ("diving", r"rebreather|diving"),
    ("modular_carrier", r"modular carrier|carrierrigkbt"),
    ("extended_armor", r"\b(?:iotv|otv|iba|mtv|osprey|6b13|6b23|6b43|6b45|6b3|6b5|md99)\b|heavy armor|heavy armour|pbb.?m.?(?:98|99|12)|\b6b armor\b"),
    ("plate_carrier", r"\b(?:mbav|mbss|rrv|spcs?|plateframe|avs|cpc|jpc|rba|falcon|protec|lbt|6094|kkz10)\b|plate.?carrier|\bplate\b|\bmlbv pc\b|carrier (?:lite|rig|special)|eagle vest"),
    ("soft_fragmentation", r"\b(?:pasgt|6b2|m1955|m1969|m69|m55)\b|\bflak\b|tactical vest|press|pilot vest|ballistic vest"),
    ("load_bearing", r"webbing|chestrig|chest rig|belt|suspender|bandol[ei]er|harness|\b(?:smersh|lifchik|chicom|alice|lbv|lc[12]|6sh\d+|vydra)\b|m1961|m1956|m1967|ammo vest|\bkit\b"),
]
UNIFORM_RULES = [
    ("virtual_reality", r"\bvr\b|virtual"), ("special_purpose", r"viper|special purpose"),
    ("cbrn", r"cbrn|hazmat"), ("diving", r"wetsuit|diver"),
    ("pilot_coveralls", r"pilot|coveralls|flight suit"),
    ("civilian_clothing", r"civilian|casual|hawai|polo|flannel|jeans?|shorts|t.?shirt|business suit|dress"),
]


def name_role(row):
    # Split class-name separators before testing complete construction tokens.
    text = re.sub(r"[_\-]", " ", row["classname"] + " " + str(get(row["properties"], "displayName", "")))
    if row["kind"] == "vest" and re.search(r"\b(?:faust|fauf)\b", text, re.I):
        return "unidentified"
    rules = VEST_RULES if row["kind"] == "vest" else UNIFORM_RULES
    return next((role for role, pattern in rules if re.search(pattern, text, re.I)),
                "unidentified" if row["kind"] == "vest" else "ordinary_clothing")


def flattened(value, prefix=()):
    """Preserve missing versus explicit null, without evaluating config text."""
    result = {}
    for key, child in value.items():
        path = prefix + (key,)
        if isinstance(child, dict):
            result.update(flattened(child, path))
        else:
            result[path] = child
    return result


def comparison_value(value):
    """Align vest regions by hitpoint name; keep unit geometry/dependencies visible."""
    if value["kind"] != "vest":
        return value
    item = value["item"]
    hp = item.get("hitpointsprotectioninfo", {})
    regions = {}
    for key, region in hp.items():
        if isinstance(region, dict):
            hit = str(region.get("hitpointname", key)).lower()
            if hit in regions:
                raise ValueError(f"Duplicate vest hitpoint: {hit}")
            regions[hit] = {k: v for k, v in region.items()
                            if k in {"armor", "passthrough", "explosionshielding"}}
    return {"item": {k: v for k, v in item.items() if k != "hitpointsprotectioninfo"}, "regions": regions}


def differences(current, reference):
    a, b = flattened(current), flattened(reference)
    return [{"path": list(path), "current_present": path in a, "reference_present": path in b,
             "current": a.get(path), "reference": b.get(path)}
            for path in sorted(a.keys() | b.keys())
            if path not in a or path not in b or a[path] != b[path]
            or isinstance(a[path], bool) != isinstance(b[path], bool)]


def build_assessments(gear, vehicles):
    lookup = {row["classname"].lower(): row for row in gear}
    unit_rows = {row["classname"].lower(): row for row in vehicles}
    units = {name: row["properties"] for name, row in unit_rows.items()}
    values = {row["classname"].lower(): protection(row, units)
              for row in gear if row["kind"] in {"vest", "uniform"}}
    catalogs = {"vest": VEST_REFERENCES, "uniform": UNIFORM_REFERENCES}
    references, reference_roles = {}, {}
    for kind, catalog in catalogs.items():
        references[kind] = {}
        for role, names in catalog.items():
            for name in names:
                row = lookup[name.lower()]
                if row["kind"] != kind or not any(addon.lower().startswith("a3_") for addon in row["sourceAddons"]):
                    raise ValueError(f"Not a loaded vanilla {kind} reference: {name}")
                value = values[name.lower()]
                if "unresolved" in value.get("unit", {}):
                    raise ValueError(f"Unresolved vanilla uniform reference: {name}")
                references[kind][name] = value
                reference_roles[name.lower()] = role
    linked = defaultdict(list)
    wearers = defaultdict(list)
    descendants = defaultdict(list)
    for row in gear:
        if row["kind"] == "uniform":
            name = get(get(row["properties"], "ItemInfo", {}), "uniformClass", "")
            linked[name.lower()].append(row["classname"])
    for row in vehicles:
        wearers[str(get(row["properties"], "uniformClass", "")).lower()].append(row["classname"])
        for parent in row["ancestry"][1:]:
            if parent.lower() in linked:
                descendants[parent.lower()].append(row["classname"])
    unit_usage = []
    for lower, uniforms in sorted(linked.items()):
        unit_row = unit_rows.get(lower)
        unit_usage.append({"unit_class": unit_row["classname"] if unit_row else get(get(lookup[uniforms[0].lower()]["properties"], "ItemInfo", {}), "uniformClass", ""),
                           "resolved": unit_row is not None, "uniforms": uniforms,
                           "descendants": descendants[lower],
                           "declared_wearers": sorted({name for uniform in uniforms for name in wearers[uniform.lower()]})})
    usage = {row["unit_class"].lower(): row for row in unit_usage}
    assessments, comparisons = [], []
    comparison_cache = {}
    for row in gear:
        kind, lower = row["kind"], row["classname"].lower()
        if kind not in catalogs:
            continue
        props = row["properties"]
        value = values[lower]
        vector = comparison_value(value)
        profile = profile_id(value)
        unresolved = "unresolved" in value.get("unit", {})
        role = reference_roles.get(lower, name_role(row))
        matches = [name for name, ref in references[kind].items() if comparison_value(ref) == vector] if not unresolved else []
        candidates = catalogs[kind].get(role, [])
        # An exact observation match is useful evidence, not a construction assignment.
        if not candidates:
            candidates = matches
        flags = []
        fields = flattened(vector)
        if any(isinstance(v, str) for path, v in fields.items()
               if path[-1] in {"armor", "armorstructural", "passthrough", "explosionshielding"}):
            flags.append("text_protection_values")
        if get(props, "scope") != 2:
            flags.append("nonpublic_or_text_scope")
        if value["item"]:
            if any(k != "hitpointsprotectioninfo" for k in value["item"]):
                flags.append("legacy_item_fields")
        if any("simulation" in region for region in value["item"].get("hitpointsprotectioninfo", {}).values() if isinstance(region, dict)):
            flags.append("mod_region_simulation_retained")
        info = get(props, "ItemInfo", {})
        unit = get(info, "uniformClass", "") if kind == "uniform" else None
        use = usage.get(str(unit).lower(), {})
        if kind == "uniform" and (len(use.get("uniforms", [])) > 1 or use.get("descendants")):
            flags.append("shared_unit_or_descendants")
        if kind == "vest" and role == "load_bearing":
            regions = vector.get("regions", {})
            if any(type(hp.get("armor")) in (int, float) and hp["armor"] > 0 or
                   type(hp.get("passthrough")) in (int, float) and hp["passthrough"] < 1 for hp in regions.values()):
                flags.append("load_bearing_has_protection")
        is_vanilla = lower.startswith(("v_", "u_")) and any(a.lower().startswith("a3_") for a in row["sourceAddons"])
        if unresolved:
            status, reason = "unresolved_uniform_unit", "Linked soldier class is absent; protection is unknown."
        elif is_vanilla:
            status, reason = "vanilla_reference_preserved", "Loaded vanilla observation is preserved, including specialized profiles."
        elif "load_bearing_has_protection" in flags:
            status, reason = "review_role_protection_conflict", "Load-bearing name has configured damage protection; inspect construction before normalization."
        elif matches:
            status, reason = "matches_vanilla_profile", "Selected exported protection fields match a loaded vanilla profile; geometry and construction are not proven equivalent."
        elif "text_protection_values" in flags:
            status, reason = "review_text_protection", "Text protection fields remain uninterpreted; compare raw values without numeric coercion."
        elif kind == "uniform" and "legacy_item_fields" in flags:
            status, reason = "review_uniform_item_fields", "Linked body profile and item-level legacy fields need separate review."
        elif candidates:
            status, reason = "review_vanilla_role_comparison", "Candidate vanilla roles are recorded; field differences are review evidence, not proposed overrides."
        else:
            status, reason = "review_construction_identity", "Construction cannot be safely assigned from the exported identity."
        assessments.append({"classname": row["classname"], "kind": kind, "role": role, "status": status,
                            "basis": "vanilla_identity" if lower in reference_roles else "name_role_hint",
                            "profile_id": profile, "candidate_references": candidates, "matching_references": matches,
                            "flags": flags, "unit_class": unit,
                            "shared_uniform_count": len(use.get("uniforms", [])) if kind == "uniform" else None,
                            "unit_descendant_count": len(use.get("descendants", [])) if kind == "uniform" else None,
                            "declared_wearer_count": len(use.get("declared_wearers", [])) if kind == "uniform" else None,
                            "reason": reason})
        if not unresolved:
            for reference in candidates:
                key = (profile, reference)
                if key not in comparison_cache:
                    comparison_cache[key] = differences(vector, comparison_value(references[kind][reference]))
                for diff in comparison_cache[key]:
                    comparisons.append({"classname": row["classname"], "reference_class": reference, **diff})
    return {"assessments": assessments, "comparisons": comparisons, "unit_usage": unit_usage,
            "summary": {"classes": dict(Counter(row["kind"] for row in assessments)),
                        "profiles": {kind: len({row["profile_id"] for row in assessments if row["kind"] == kind}) for kind in catalogs},
                        "statuses": dict(Counter(row["status"] for row in assessments)),
                        "roles": {kind: dict(Counter(row["role"] for row in assessments if row["kind"] == kind)) for kind in catalogs},
                        "comparison_rows": len(comparisons), "unit_usage_rows": len(unit_usage),
                        "unresolved_uniforms": sum(row["status"] == "unresolved_uniform_unit" for row in assessments),
                        "automatic_field_changes": 0}}
