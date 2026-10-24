"""Build the local, unsigned config-only balance pilot: helmets, vests, uniform units and ammunition.

Usage: python build_balance_pilot.py [folder]   (default: balance-pilot)
Every proposed wearable value must equal a clean vanilla value; ammunition anchors must match clean
vanilla except the declared preset-loaded references. Classes are materialized as in the verified
helmet pilot, and the in-game verifier is split into paste-sized parts.
"""
from collections import defaultdict
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3

from build_helmet_pilot import identifier, literal, pack_files, render_properties
from compare_clean_baseline import CLEAN_SNAPSHOT, compare
from extract_rpt import get

ADDON = "a3bal_pilot"
MOD = "@A3Balance_Pilot"
PART_LIMIT = 3300000
SESSION_LINE = '[] execVM "\\a3bal_pilot\\tests\\run.sqf";'
# kind -> section and the class whose observed contents are materialized (None: top-level fields only)
SCOPES = {"headgear": ("CfgWeapons", "ItemInfo"), "vest": ("CfgWeapons", "ItemInfo"),
          "uniform_unit": ("CfgVehicles", "HitPoints"), "projectile": ("CfgAmmo", None)}
CONTAINER_PARENTS = {"CfgWeapons": {"ItemInfo", "HeadgearItem", "VestItem"}, "CfgVehicles": {"HitPoints"}}
TOP_LEVEL = {"CfgWeapons": ["HeadgearItem", "VestItem"]}
BASE_ADDONS = {"CfgWeapons": "A3_Characters_F", "CfgVehicles": "A3_Characters_F", "CfgAmmo": "A3_Weapons_F"}
AMMO_FIELDS = ("hit", "caliber", "typicalspeed")
UNIFORM_UNITS = {"U_B_CombatUniform_mcam": "B_Soldier_F", "U_C_Poloshirt_blue": "C_man_polo_1_F"}
# ACE ballistics sets the loaded 7.62x54R reference speed (835; clean vanilla 800). The ladder uses the
# loaded value because the patch only runs in this preset, and the range test measured that round.
LOADED_REFERENCE = {("b_762x54_ball", "typicalspeed"): "ace_ballistics"}


def allowed(kind, path):
    lower = [part.lower() for part in path]
    if kind in ("headgear", "vest"):
        return len(lower) == 4 and lower[:2] == ["iteminfo", "hitpointsprotectioninfo"] and lower[3] in {"armor", "passthrough"}
    if kind == "uniform_unit":
        return len(lower) == 3 and lower[0] == "hitpoints" and lower[2] in {"armor", "passthrough", "explosionshielding"}
    return len(lower) == 1 and lower[0] in AMMO_FIELDS


def close(a, b):
    return type(a) in (int, float) and type(b) in (int, float) and abs(a - b) <= max(1e-6, abs(b) * 1e-6)


def clean_values(root, names):
    """Clean vanilla number fields for the anchor classes, from both clean captures."""
    values = {}
    capture = json.loads((root / "validation/clean-vanilla-capture.json").read_text(encoding="utf-8"))
    for _, section, name, path, kind, value in capture["fields"]:
        if kind == "number":
            values[(section, name.lower(), tuple(part.lower() for part in path))] = value
    with closing(sqlite3.connect(f"file:{root / CLEAN_SNAPSHOT}?mode=ro", uri=True)) as clean:
        mode = json.loads(clean.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()[0])
        mods = json.loads(clean.execute("SELECT value FROM metadata WHERE key='loaded_mods'").fetchone()[0])
        if mode != "clean" or any(row[2] is not True for row in mods):
            raise ValueError("Second clean capture has non-official mods")
        for section, name in sorted(names):
            for path, value in clean.execute("SELECT path, value FROM fields WHERE section=? AND classname=? AND kind='number'", (section, name)):
                key = (section, name.lower(), tuple(part.lower() for part in json.loads(path)))
                if values.setdefault(key, json.loads(value)) != json.loads(value):
                    raise ValueError(f"The two clean captures disagree: {key}")
    return values


def untraced(records, changes, clean):
    """Proposed values that are not a clean vanilla value (wearables) or rest on drifted anchors (ammunition)."""
    regions = {key[:2] + key[2][:3] for key in clean}
    captured = {key[:2] for key in clean}
    problems = []
    for edit in changes:
        if edit["kind"] == "projectile":
            continue
        anchor = edit["anchors"][0]
        name = (UNIFORM_UNITS.get(anchor, anchor) if edit["kind"] == "uniform_unit" else anchor).lower()
        path = tuple(part.lower() for part in edit["path"])
        value = clean.get((edit["section"], name, path))
        # Vanilla omits a region entirely on load-bearing rigs: that region gets no protection.
        absent = (edit["section"], name) in captured and len(path) == 4 and (edit["section"], name) + path[:3] not in regions and (
            (path[-1], edit["proposed"]) in {("armor", 0), ("passthrough", 1)})
        if not absent and not close(edit["proposed"], value):
            problems.append(edit)
    ammo = {row["classname"].lower(): row for row in records if row["section"] == "CfgAmmo"}
    for anchor in sorted({edit["anchors"][0] for edit in changes if edit["kind"] == "projectile"}):
        row = ammo[anchor.lower()]
        for field in AMMO_FIELDS:
            observed = next(value for key, value in row["properties"].items() if key.lower() == field)
            source = LOADED_REFERENCE.get((anchor.lower(), field))
            if not close(observed, clean.get(("CfgAmmo", anchor.lower(), (field,)))) and source not in row["sourceAddons"]:
                problems.append({"classname": anchor, "path": [field], "observed": observed})
    return problems


def tree(props):
    nodes = []
    for key, value in props.items():
        if key == "$parent":
            continue
        if isinstance(value, dict):
            nodes.append([key, "class", tree(value)])
        else:
            nodes.append([key, "array" if isinstance(value, list) else "text" if isinstance(value, str) else "number", value])
    return nodes


def count(nodes):
    return sum(1 + (count(value) if kind == "class" else 0) for _, kind, value in nodes)


def section_plan(section, records, edits):
    container = SCOPES[edits[0]["kind"]][1]
    lookup = {row["classname"].lower(): row for row in records if row["section"] == section}
    targeted = {row["classname"].lower() for row in edits}
    affected = {name for name, row in lookup.items() if name in targeted or any(parent.lower() in targeted for parent in row["ancestry"][1:])}
    expected = {name: copy.deepcopy(lookup[name]["properties"]) for name in affected}
    changed = defaultdict(set)
    for edit in edits:
        node = expected[edit["classname"].lower()]
        for key in edit["path"][:-1]:
            node = node[key]
        if node[edit["path"][-1]] != edit.get("old_text", edit["old"]):
            raise ValueError(f"Proposal no longer matches observed input: {edit['classname']}")
        node[edit["path"][-1]] = edit["proposed"]
        changed[edit["classname"].lower()].add(edit["path"][0].lower())
    ordered, visiting, visited, external = [], set(), set(), []
    def visit(name, spelled):
        if name in visited:
            return
        if name in visiting:
            raise ValueError(f"Cyclic {section} ancestry: {name}")
        visited.add(name)
        if name not in lookup:
            # Engine root classes outside the export (Land, AllVehicles, All) are only declared.
            external.append(identifier(spelled))
            return
        visiting.add(name)
        row = lookup[name]
        identifier(row["classname"])
        if len(row["ancestry"]) > 1:
            visit(row["ancestry"][1].lower(), row["ancestry"][1])
        visiting.remove(name)
        ordered.append(name)
    for name in sorted(affected):
        visit(name, lookup[name]["classname"])
    if any(name in affected and len(lookup[name]["ancestry"]) > 1 and lookup[name]["ancestry"][1] in external for name in ordered):
        raise ValueError(f"An affected {section} class has an unexported parent")
    lines, checks = ["class " + section, "{"] + [f"    class {name};" for name in TOP_LEVEL.get(section, []) + external], []
    for name in ordered:
        row = lookup[name]
        parent = ": " + identifier(row["ancestry"][1]) if len(row["ancestry"]) > 1 else ""
        props = expected.get(name, row["properties"])
        if container:
            info = get(props, container)
            nodes = [[container, "class", tree(info)]] if isinstance(info, dict) else []
            if name not in affected:
                lines.append(f'    class {row["classname"]}{parent} {{ class {container}; }};' if nodes else
                             f'    class {row["classname"]}{parent} {{}};' if parent else f'    class {row["classname"]};')
            else:
                if not nodes or info.get("$parent") not in CONTAINER_PARENTS[section]:
                    raise ValueError(f"Unsupported {container} inheritance: {row['classname']}")
                lines += [f'    class {row["classname"]}{parent}', "    {", f'        class {container}: {info["$parent"]}', "        {"]
                lines.extend(render_properties(info, "            "))
                lines += ["        };", "    };"]
        else:
            # Each changed terminal field is written on every affected class: own target, else the observed value.
            fields = set().union(*(changed[ancestor.lower()] for ancestor in row["ancestry"])) if name in affected else set(AMMO_FIELDS)
            values = {key: value for key, value in props.items() if key.lower() in fields}
            if name in affected and len(values) != len(fields):
                raise ValueError(f"Retained ammunition field is absent: {row['classname']}")
            nodes = [[key, "number", value] for key, value in values.items()]
            if name not in affected:
                lines.append(f'    class {row["classname"]}{parent} {{}};' if parent else f'    class {row["classname"]};')
            else:
                lines += [f'    class {row["classname"]}{parent}', "    {"] + [f"        {identifier(key)} = {literal(value)};" for key, value in values.items()] + ["    };"]
        checks.append([section, row["classname"], row["ancestry"], nodes])
    lines += ["};"]
    summary = {"target_classes": len(targeted), "preserved_descendant_classes": len(affected - targeted),
               "checked_ancestor_classes": len(ordered) - len(affected), "changed_fields": len(edits)}
    dependencies = {addon for name in ordered for addon in lookup[name]["sourceAddons"]} | {BASE_ADDONS[section]}
    return lines, checks, summary, dependencies


def make_plan(records, changes, baseline, clean):
    if not baseline["helmet_baseline_ready"]:
        raise ValueError("Clean helmet reference comparison has not passed")
    for edit in changes:
        if edit["kind"] not in SCOPES or edit["section"] != SCOPES[edit["kind"]][0] or not allowed(edit["kind"], edit["path"]):
            raise ValueError(f"Edit escapes the selected protection/terminal scope: {edit['classname']} {edit['path']}")
    problems = untraced(records, changes, clean)
    if problems:
        raise ValueError(f"{len(problems)} proposed values do not trace to clean vanilla, e.g. {problems[0]['classname']} {problems[0]['path']}")
    patches = {row["classname"].lower() for row in records if row["section"] == "CfgPatches"}
    body, checks, scope, dependencies = [], [], {}, set()
    for section in ("CfgWeapons", "CfgVehicles", "CfgAmmo"):
        edits = [edit for edit in changes if edit["section"] == section]
        if not edits:
            continue
        lines, section_checks, summary, needed = section_plan(section, records, edits)
        body += lines
        checks += section_checks
        dependencies |= needed
        for kind in sorted({edit["kind"] for edit in edits}):
            scope[kind] = {"target_classes": len({edit["classname"].lower() for edit in edits if edit["kind"] == kind}),
                           "changed_fields": sum(edit["kind"] == kind for edit in edits)}
        scope[section] = summary
    dependencies = sorted(dependencies)
    if any(name.lower() not in patches for name in dependencies):
        raise ValueError("A required addon is absent from the observed CfgPatches snapshot")
    build_id = hashlib.sha256(json.dumps([baseline["capture_sha256"], changes, checks, dependencies], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    lines = ["// Local balance pilot: helmets, vests, uniform units, ammunition. Full-preset snapshot; see the manifest.",
             "class CfgPatches", "{", f"    class {ADDON}", "    {", '        name = "A3 Balance Pilot";', '        author = "Local balance project";',
             "        requiredVersion = 2.22;", "        requiredAddons[] = " + literal(dependencies) + ";",
             "        units[] = {};", "        weapons[] = {};", "        buildId = " + literal(build_id) + ";", "    };", "};"] + body + [""]
    manifest = {"build_id": build_id, "status": "built locally; NOT in-game validated", "scope": "helmets, vests, uniform units, ammunition",
                "clean_capture_sha256": baseline["capture_sha256"], "by_kind": scope, "changed_fields": len(changes),
                "checked_classes": len(checks), "verified_fields_expected": sum(count(check[3]) for check in checks),
                "required_addons": dependencies, "loaded_references": [list(key) + [source] for key, source in LOADED_REFERENCE.items()],
                "numeric_tolerance": "max(1e-6, abs(expected)*1e-6)",
                "limitation": "Snapshot materializes ItemInfo/HitPoints; use only with the original full preset and regenerate after updates."}
    return "\n".join(lines), checks, manifest


def sqf(value):
    # SQF array literals use doubled quotes, not JSON backslash escapes.
    if isinstance(value, list):
        return "[" + ",".join(sqf(item) for item in value) + "]"
    return literal(value)


def split(checks, limit=PART_LIMIT):
    parts, size = [[]], 0
    for check in checks:
        length = len(sqf(check)) + 1
        if parts[-1] and size + length > limit:
            parts.append([])
            size = 0
        parts[-1].append(check)
        size += length
    return parts


def build(root, destination=None):
    destination = destination or root / "balance-pilot"
    if destination.exists():
        raise ValueError(f"{destination.name} already exists; refusing to overwrite a reviewable build")
    baseline = compare(root)
    with (root / "data-recovered/configs.relevant.jsonl").open(encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream]
    changes = json.loads((root / "proposal/change_ledger.json").read_text())
    anchors = {(edit["section"], (UNIFORM_UNITS.get(a, a) if edit["kind"] == "uniform_unit" else a)) for edit in changes for a in edit["anchors"][:1]}
    config, checks, manifest = make_plan(records, changes, baseline, clean_values(root, anchors))
    config_bytes = config.encode("utf-8")
    template = (root / "verify_balance_pilot.template.sqf").read_text()
    parts = split(checks)
    scripts = []
    for number, part in enumerate(parts, 1):
        script = (template.replace("__BUILD_ID__", manifest["build_id"]).replace("__PART__", str(number))
                  .replace("__PARTS__", str(len(parts))).replace("__CHECKS__", sqf(part)))
        scripts.append(script)
        manifest.setdefault("parts", []).append({"part": number, "script": f"verify_part{number}.sqf", "classes": len(part),
                                                 "fields": sum(count(check[3]) for check in part),
                                                 "sha256": hashlib.sha256(script.encode()).hexdigest()})
    # The session scripts travel inside the PBO, so one console line runs every check and the acceptance test.
    acceptance = json.loads((root / "validation/acceptance-test/manifest.json").read_text(encoding="utf-8"))
    acceptance_script = (root / "validation/acceptance-test" / acceptance["script"]["file"]).read_bytes()
    if hashlib.sha256(acceptance_script).hexdigest() != acceptance["script"]["sha256"]:
        raise ValueError("Acceptance test script differs from its manifest; rerun prepare_acceptance_test.py")
    launcher = (root / "run_pilot_session.template.sqf").read_text().replace("__PARTS__", str(len(parts))).encode("utf-8")
    files = [("config.cpp", config_bytes)] + [(f"tests\\verify_part{number}.sqf", script.encode("utf-8")) for number, script in enumerate(scripts, 1)]
    files += [("tests\\acceptance_test.sqf", acceptance_script), ("tests\\run.sqf", launcher)]
    archive = pack_files(files, ADDON)
    manifest["session"] = {"console_line": SESSION_LINE, "acceptance_suite_id": acceptance["suite_id"],
                           "acceptance_trials": acceptance["expected_results"], "acceptance_blast_trials": acceptance["expected_blast_results"],
                           "packed_files": {name: hashlib.sha256(data).hexdigest() for name, data in files}}
    manifest.update(pbo_sha256=hashlib.sha256(archive).hexdigest(), config_sha256=hashlib.sha256(config_bytes).hexdigest(),
                    source_export_sha256=hashlib.sha256((root / "data-recovered/configs.relevant.jsonl").read_bytes()).hexdigest())
    destination.mkdir()
    source = destination / "source" / ADDON
    source.mkdir(parents=True)
    (source / "config.cpp").write_bytes(config_bytes)
    mod = destination / MOD
    (mod / "addons").mkdir(parents=True)
    (mod / f"addons/{ADDON}.pbo").write_bytes(archive)
    (mod / "mod.cpp").write_text('name = "A3 Balance Pilot";\ndescription = "Local config pilot: helmets, vests, uniforms and ammunition";\n', encoding="utf-8")
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (destination / "expected-config.json").write_text(json.dumps(checks, ensure_ascii=False), encoding="utf-8")
    for number, script in enumerate(scripts, 1):
        (destination / f"verify_part{number}.sqf").write_text(script, encoding="utf-8", newline="")
    # Paste fallback if execVM from the PBO is unavailable; the same bytes are packed.
    (destination / "acceptance_test.sqf").write_bytes(acceptance_script)
    return manifest


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parent
    result = build(root, root / sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps({key: result[key] for key in ("build_id", "by_kind", "checked_classes", "verified_fields_expected", "parts", "pbo_sha256")}, indent=2))
