"""Vanilla-anchored terminal targets for rifle ball and its derived specialized ladder."""
from collections import Counter
import math
import re

from extract_rpt import get


FIELDS = ("hit", "caliber", "typicalSpeed")
FAMILIES = [
    ("556x45", "5.56x45", "B_556x45_Ball", "rhs_ammo_556x45_M855_Ball"),
    ("545x39", "5.45x39", "B_545x39_Ball_F", "rhs_B_545x39_Ball"),
    ("762x39", "7.62x39", "B_762x39_Ball_F", "rhs_B_762x39_Ball"),
    ("762x51", "7.62x51", "B_762x51_Ball", "rhs_ammo_762x51_M80_Ball"),
    ("762x54", "7.62x54R", "B_762x54_Ball", "rhs_B_762x54_Ball"),
]
# Explicit ordinary-ball gameplay equivalents; specialized variants use the ladder below.
ORDINARY_BALL = {"rhs_ammo_556x45_m855_ball", "rhs_b_545x39_ball",
                 "rhs_b_762x39_ball", "rhs_ammo_762x51_m80_ball", "rhs_b_762x54_ball"}
# These shortened classnames inherit the matching full-cartridge vanilla roots.
SHORT_GENERIC = {
    "UK3CB_BAF_556_Ball": "556x45",
    "UK3CB_BAF_556_Ball_Tracer_Red": "556x45",
    "UK3CB_BAF_762_Ball": "762x51",
    "UK3CB_BAF_762_Ball_Tracer_Red": "762x51",
}
# Derived v7 gameplay ladder: caliber multiplier on the vanilla ball of the same
# cartridge. AP uses the median ratio of the ACE/BWA3 AP rounds, which are already
# defined on the vanilla scale (M993 2.2/1.6, M995 1.6/0.87, BWA3 2.4/1.6, 1.4/0.87).
LADDER = {"ball_named": 1.0, "match_named": 1.0, "enhanced_ball_named": 1.2, "armor_piercing_named": 1.5}
# A round keeps its own author's damage ratio to that mod's ball, within these limits.
HIT_RATIO_LIMITS = (.75, 1.5)
# 3CB ammunition derives from RHS values; other mods are defined on the vanilla scale.
RHS_SCALE_PREFIXES = ("rhs_", "rhssaf_", "uk3cb_")
CARTRIDGE = re.compile(r"(?<!\d)(\d{1,3})x(\d{1,3})(?:mm)?r?(?!\d)", re.I)
EXCLUDED = re.compile(r"(?:^|_)(?:blank|training|dummy|rubber|paintball|minigun|splash|dual|er7)(?:_|$)", re.I)
SPECIAL = re.compile(r"(?:^|_)(ap|api|epr|sost|spr|sd|subsonic|lr|sc|trcd|l42a1|b416|7[a-z]+\d+|mk\d+|m\d+[a-z0-9]*)(?=_|$)", re.I)
GENERIC_SUFFIXES = {"ball", "tracer", "tracers", "red", "green", "yellow", "white", "orange", "dim", "f"}
# User decision (2026-10-20): vehicle-mounted MGs fire the same normalized rifle rounds as infantry.
FIRED = {"handheld_only", "vehicle_shared"}
USABLE = FIRED | {"no_magazines"}
# v8 identifications from magazine names and ballistics where the classname has no designator.
IDENTIFIED = {
    "rhs_b_762x39_ball_89": "ball_named",     # magazines "57-N-231(89)": standard steel-core ball
    "ffp_b_762x39_rk": "ball_named",          # "RK Mag" for the Rk 62/95: Finnish service ball
    "rhssaf_ammo_556x45_spr": "match_named",  # Special Purpose Rifle load; no magazines in the preset
    "vtn_762x51_ball_sc": "ball_named",       # 9.46 g bullet, the M80 ball weight
    "vtn_762x51_ball_trcd": "ball_named",     # nvgOnly dim tracer derived from the SC ball
}


def cartridge(name):
    found = {match[1] + "x" + match[2] for match in CARTRIDGE.finditer(name)}
    return next(iter(found)) if len(found) == 1 else None


def triplet(row):
    return {field: get(row["properties"], field) for field in FIELDS}


def numeric_triplet(row):
    return all(type(value) in (int, float) and math.isfinite(value) and value > 0
               for value in triplet(row).values())


def kinetic(row):
    p = row["properties"]
    return get(p, "explosive") == 0 and get(p, "indirectHit") == 0 and not get(p, "submunitionAmmo", "")


def generic_name(name):
    matches = list(CARTRIDGE.finditer(name))
    if len(matches) != 1:
        return False
    suffix = name[matches[0].end():].strip("_").lower().split("_")
    return bool(suffix) and all(token in GENERIC_SUFFIXES for token in suffix)


def special_tokens(name):
    return {match[1].lower() for match in SPECIAL.finditer(name)}


def role(row):
    name = row["classname"].lower()
    if name in IDENTIFIED:
        return IDENTIFIED[name]
    if re.search(r"(?:^|_)(?:sd|subsonic|7u1|u_ball)(?:_|$)", name):
        return "subsonic_named"
    # GRAU designators are recognized explicitly: 7N22/7N24/7BZ3 are AP constructions.
    if re.search(r"(?:^|_)(?:ap|api|m61|m993|m995|7n22|7n24|7bz3)(?:_|$)", name):
        return "armor_piercing_named"
    if "epr" in name or "m855a1" in name or re.search(r"(?:^|_)(?:7n10|7n13|7n26|sost|mk318|mk319)(?:_|$)", name):
        return "enhanced_ball_named"
    if re.search(r"(?:^|_)(?:mk262|mk316|m118(?:lr)?|7n1|7n14|lr)(?:_|$)", name):
        return "match_named"
    if re.search(r"(?:^|_)(?:7n6|m193|m196|m855|m62|7t2)(?:_|$)", name):
        return "ball_named"
    return "named_variant" if special_tokens(name) else "generic_ball"


def ladder_role(row, code, scale):
    """Own designator first, else the nearest same-cartridge specialized ancestor."""
    own = role(row)
    if own in LADDER or own == "subsonic_named":
        return own
    for parent in row["ancestry"][1:]:
        lower = parent.lower()
        if cartridge(parent) == code and lower not in ORDINARY_BALL and lower != scale["vanilla_anchor"].lower():
            inherited = role({"classname": parent})
            if inherited in LADDER or inherited == "subsonic_named":
                return inherited
    return own


def reference_ball(row, code, scale, lookup):
    """The ordinary ball that the round's own author scaled it against."""
    for parent in row["ancestry"][1:]:
        lower = parent.lower()
        if cartridge(parent) == code and lower in ORDINARY_BALL and lower in lookup:
            return lookup[lower]
    # Config ancestry often reaches the vanilla class; the author's scale follows the mod.
    name = scale["rhs_anchor"] if row["classname"].lower().startswith(RHS_SCALE_PREFIXES) else scale["vanilla_anchor"]
    return lookup[name.lower()]


def coefficient(values):
    return values["hit"] / values["typicalSpeed"]


def build_ammunition_policy(all_ammo, *, verified_handheld_projectiles=(), usage=None):
    ammo = [row for row in all_ammo if get(row["properties"], "simulation") == "shotBullet"]
    lookup = {row["classname"].lower(): row for row in ammo}
    scales = {}
    for code, label, vanilla_name, rhs_name in FAMILIES:
        vanilla, rhs = lookup[vanilla_name.lower()], lookup[rhs_name.lower()]
        if cartridge(vanilla_name) != code or cartridge(rhs_name) != code:
            raise ValueError(f"Cartridge mismatch in family anchor: {label}")
        if not all(numeric_triplet(row) and kinetic(row) for row in (vanilla, rhs)):
            raise ValueError(f"Unsupported terminal values in family anchor: {label}")
        v, r = triplet(vanilla), triplet(rhs)
        scales[code] = {"code": code, "cartridge": label, "vanilla_anchor": vanilla_name,
                        "rhs_anchor": rhs_name, "vanilla_coefficient": coefficient(v),
                        "rhs_coefficient": coefficient(r), "hit_multiplier": 1,
                        "target_hit": v["hit"], "target_caliber": v["caliber"],
                        "target_typical_speed": v["typicalSpeed"],
                        "assumption": "Loaded vanilla ordinary-ball terminal triplet is the ball target; specialized rounds use the derived ladder relative to it."}
    usage = {name.lower(): value for name, value in (usage or {}).items()}
    admitted = {name.lower() for name in verified_handheld_projectiles}

    def verdict(lower):
        if lower in usage:
            return usage[lower]["verdict"]
        return "handheld_only" if lower in admitted else "unproven"

    short = {name.lower(): code for name, code in SHORT_GENERIC.items()}
    entries = []
    for row in ammo:
        name = row["classname"]
        lower = name.lower()
        code = cartridge(name) or short.get(lower)
        scale = scales.get(code)
        entry = {"row": row, "code": code, "scale": scale, "basis": "unassigned", "candidate": None,
                 "ladder_role": None, "reference_ball": None, "ratio": None,
                 "status": "review_cartridge_identity", "reason": "No unambiguous supported cartridge identity."}
        entries.append(entry)
        if lower.startswith("b_") and any(addon.lower().startswith("a3_") for addon in row["sourceAddons"]) and (scale is None or lower != scale["vanilla_anchor"].lower()):
            entry.update(status="reference_preserved", reason="Loaded vanilla class is part of the baseline and remains unchanged.")
        elif EXCLUDED.search(name):
            entry.update(status="preserved_special_function", reason="Blank, training, underwater/dual-purpose, or dedicated vehicle/splash identity is excluded.")
        elif code and scale is None:
            entry.update(status="preserved_outside_scale", reason="Cartridge has no selected vanilla family anchor in this pass.")
        elif scale is not None:
            vanilla = lookup[scale["vanilla_anchor"].lower()]
            if not numeric_triplet(row) or not kinetic(row):
                entry.update(status="review_terminal_model", reason="Missing/text terminal values, explosion, indirect damage, or submunition behavior require a separate model.")
            elif lower == scale["vanilla_anchor"].lower():
                entry.update(basis="vanilla_reference", candidate=triplet(row), status="matches_target",
                             reason="Loaded vanilla ordinary ball is the cartridge reference.")
            else:
                named_ancestors = [parent for parent in row["ancestry"][1:]
                                   if cartridge(parent) == code and special_tokens(parent)
                                   and parent.lower() not in ORDINARY_BALL]
                if (special_tokens(name) and lower not in ORDINARY_BALL) or lower in IDENTIFIED or named_ancestors or get(row["properties"], "typicalSpeed") < 400:
                    found = ladder_role(row, code, scale)
                    entry["ladder_role"] = found
                    if found == "subsonic_named" or get(row["properties"], "typicalSpeed") < 400:
                        entry.update(status="preserved_subsonic_observed", reason="Subsonic rounds keep observed values; their caliber is checked against the ball target.")
                    elif found in LADDER:
                        reference = reference_ball(row, code, scale, lookup)
                        if not numeric_triplet(reference):
                            entry.update(status="review_variant_identity", reason="The round's own ordinary-ball reference has no numeric terminal values.")
                        else:
                            low, high = HIT_RATIO_LIMITS
                            ratio = min(high, max(low, coefficient(triplet(row)) / coefficient(triplet(reference))))
                            v = triplet(vanilla)
                            entry.update(basis="derived_specialized_ladder", reference_ball=reference["classname"], ratio=ratio,
                                         candidate={"hit": round(v["hit"] * ratio, 4), "caliber": round(v["caliber"] * LADDER[found], 6),
                                                    "typicalSpeed": v["typicalSpeed"]},
                                         reason=f"Derived ladder: vanilla ball caliber x{LADDER[found]} for {found}; hit keeps the author's ratio to {reference['classname']}.")
                    else:
                        entry.update(status="review_variant_identity", reason="Specialized designator is not identified; it blocks its cartridge until named.")
                elif generic_name(name) or lower in short or lower in ORDINARY_BALL:
                    if lower in short and scale["vanilla_anchor"].lower() not in {parent.lower() for parent in row["ancestry"]}:
                        raise ValueError(f"Shortened cartridge alias lost its expected anchor: {name}")
                    entry.update(basis="vanilla_ordinary_ball_equivalent", candidate=triplet(vanilla),
                                 reason="Use the loaded vanilla ordinary-ball hit, caliber, and typicalSpeed; retain other projectile behavior.")
                else:
                    entry.update(status="review_variant_identity", reason="Cartridge is known but the projectile variant is not safely identified.")
            if entry["candidate"] is not None and cartridge(scale["vanilla_anchor"]) != code:
                raise ValueError(f"Cross-cartridge target rejected: {name}")

    # A cartridge is released whole: every member must be identified and its use established.
    readiness = {}
    for code, scale in scales.items():
        members = [e for e in entries if e["code"] == code and e["basis"] not in ("unassigned", "vanilla_reference")
                   and any(get(e["row"]["properties"], field) != e["candidate"][field] for field in FIELDS)]
        unknown = [e for e in entries if e["code"] == code and e["status"] == "review_variant_identity"]
        blockers = [f"unidentified {e['row']['classname']}" for e in unknown if verdict(e["row"]["classname"].lower()) != "no_magazines"]
        blockers += [f"{verdict(e['row']['classname'].lower())} {e['row']['classname']}" for e in members
                     if verdict(e["row"]["classname"].lower()) not in USABLE]
        readiness[code] = {"cartridge": scale["cartridge"], "ready": not blockers, "members": len(members), "blockers": blockers}

    mapping, changes = [], []
    for entry in entries:
        row, code, scale = entry["row"], entry["code"], entry["scale"]
        name = row["classname"]
        target, candidate = None, entry["candidate"]
        if entry["basis"] == "vanilla_reference":
            target, candidate = candidate, None
        elif candidate is not None:
            own = verdict(name.lower())
            differs = any(get(row["properties"], field) != candidate[field] for field in FIELDS)
            if not differs:
                target, candidate = candidate, None
                entry.update(status="matches_target")
            elif readiness[code]["ready"] and own in FIRED:
                target, candidate = candidate, None
                rule = "derived_specialized_ladder" if entry["basis"] == "derived_specialized_ladder" else "vanilla_rifle_terminal_scale"
                for field in FIELDS:
                    old = get(row["properties"], field)
                    if old != target[field]:
                        changes.append({"section": "CfgAmmo", "classname": name, "kind": "projectile",
                                        "path": [next(key for key in row["properties"] if key.lower() == field.lower())],
                                        "old": old, "proposed": target[field], "rule": rule,
                                        "anchors": [scale["vanilla_anchor"]],
                                        "confidence": entry["basis"], "reason": entry["reason"], "sourceAddons": row["sourceAddons"]})
                entry["status"] = "proposed_change"
            elif own == "no_magazines":
                entry.update(status="deferred_no_magazine_evidence", reason="No magazine loads this projectile in the full capture; unknown script use keeps it unchanged.")
            elif own not in USABLE:
                entry.update(status="deferred_handheld_usage_proof", reason="Its use is not established from the capture (" + own + ").")
            else:
                entry.update(status="deferred_cartridge_incomplete", reason="Usable, but its cartridge is released whole and still has blockers: " + "; ".join(readiness[code]["blockers"][:3]))
        mapping.append({"classname": name, "cartridge_code": code, "cartridge": scale["cartridge"] if scale else code,
                        "role": role(row) if entry["basis"] != "vanilla_ordinary_ball_equivalent" else "generic_ball",
                        "ladder_role": entry["ladder_role"],
                        "tracer_name_flag": bool(re.search("trac|m62_|m196_|7t2|7bt3", name.lower())),
                        "status": entry["status"], "basis": entry["basis"],
                        "reference_class": scale["vanilla_anchor"] if entry["basis"] != "unassigned" else None,
                        "reference_ball": entry["reference_ball"],
                        "hit_multiplier": entry["ratio"] if entry["ratio"] is not None else (1 if entry["basis"] != "unassigned" else None),
                        "usage_verdict": verdict(name.lower()) if code in scales else None,
                        "current": triplet(row), "proposed": target, "candidate": candidate, "reason": entry["reason"]})
    changed = {row["classname"].lower() for row in changes}
    mapped = {row["classname"].lower() for row in mapping if row["proposed"] is not None}
    guards = []
    for row in all_ammo:
        ancestors = [name for name in row["ancestry"][1:] if name.lower() in changed]
        if ancestors and row["classname"].lower() not in mapped:
            guards.append({"classname": row["classname"], "simulation": get(row["properties"], "simulation"),
                           "changed_ancestors": ancestors, "retain": triplet(row),
                           "reason": "Retain observed terminal values if a later patch changes inherited defaults; declaration ownership is unknown."})
    by_name = {row["classname"].lower(): row for row in mapping}
    penetration_checks = []
    for entry in entries:
        row, code = entry["row"], entry["code"]
        if code is None:
            continue
        if code in scales:
            selected_role = entry["ladder_role"] or ladder_role(row, code, scales[code])
        else:
            names = [row["classname"]] + [name for name in row["ancestry"][1:] if cartridge(name) == code]
            selected_role = next((role({"classname": name}) for name in names
                                  if role({"classname": name}) in {"armor_piercing_named", "subsonic_named", "enhanced_ball_named"}), None)
        if selected_role not in {"armor_piercing_named", "subsonic_named", "enhanced_ball_named"}:
            continue
        expectation = "subsonic <= ball" if selected_role == "subsonic_named" else ("AP >= ball" if selected_role == "armor_piercing_named" else "enhanced >= ball")
        current = get(row["properties"], "caliber")
        check = {"classname": row["classname"], "cartridge": scales[code]["cartridge"] if code in scales else code,
                 "role": selected_role, "observed_penetration": current, "candidate_ball_penetration": None,
                 "ladder_penetration": None, "expectation": expectation}
        if code not in scales:
            penetration_checks.append({**check, "status": "review_no_selected_ball_anchor", "ladder_status": ""})
            continue
        ball = scales[code]["target_caliber"]
        valid = type(current) in (int, float) and math.isfinite(current)
        passes = valid and (current <= ball if selected_role == "subsonic_named" else current >= ball)
        item = by_name[row["classname"].lower()]
        ladder = (item["proposed"] or item["candidate"] or {}).get("caliber") if item["basis"] == "derived_specialized_ladder" else (current if selected_role == "subsonic_named" else None)
        ladder_ok = ladder is not None and (ladder <= ball if selected_role == "subsonic_named" else ladder >= ball)
        penetration_checks.append({**check, "candidate_ball_penetration": ball, "ladder_penetration": ladder,
                                   "status": "passes_candidate_ball_check" if passes else "review_penetration_order" if valid else "review_non_numeric_penetration",
                                   "ladder_status": "ladder_passes" if ladder_ok else "ladder_not_assigned" if ladder is None else "ladder_violation"})
    return {"version": 5, "penetration_checks": penetration_checks, "families": list(scales.values()), "mapping": mapping,
            "changes": changes, "preservation_guards": guards, "cartridges": list(readiness.values()),
            "summary": {"bullet_classes": len(ammo), "mapped_classes": len(mapped),
                        "proposed_classes": len(changed), "field_changes": len(changes),
                        "preservation_guards": len(guards),
                        "ready_cartridges": [r["cartridge"] for r in readiness.values() if r["ready"]],
                        "statuses": dict(Counter(row["status"] for row in mapping)),
                        "mapping_bases": dict(Counter(row["basis"] for row in mapping if row["basis"] != "unassigned"))}}
