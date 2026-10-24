"""Build the local test mod: the per-mod balance patches exactly as they will ship, plus a tests addon.

Usage: python build_balance_pilot.py [folder]   (default: balance-pilot)
Every proposed wearable value must equal a clean vanilla value; ammunition anchors must match clean
vanilla except the declared preset-loaded references. The patches come from build_patch.py. The tests
addon carries the config checks (split into parts), the damage test and a one-line launcher.
"""
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from build_helmet_pilot import literal, pack_files
from build_patch import PREFIX, build as build_patch
from compare_clean_baseline import CLEAN_SNAPSHOT, compare
from predict_rebinds import bound_model, predict

TESTS = f"{PREFIX}_tests"
MOD = "@A3Balance_Pilot"
PART_LIMIT = 3300000
SESSION_LINE = f'[] execVM "\\{TESTS}\\tests\\run.sqf";'
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


def count(nodes):
    return sum(1 + (count(value) if kind == "class" else 0) for _, kind, value in nodes)


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


def gate(root, changes):
    """The checks every build passes before any file is written."""
    for edit in changes:
        if not allowed(edit["kind"], edit["path"]):
            raise ValueError(f"Edit escapes the protection/terminal scope: {edit['classname']} {edit['path']}")
    baseline = compare(root)
    if not baseline["helmet_baseline_ready"]:
        raise ValueError("Clean helmet reference comparison has not passed")
    with (root / "data-recovered/configs.relevant.jsonl").open(encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream]
    anchors = {(edit["section"], (UNIFORM_UNITS.get(a, a) if edit["kind"] == "uniform_unit" else a)) for edit in changes for a in edit["anchors"][:1]}
    problems = untraced(records, changes, clean_values(root, anchors))
    if problems:
        raise ValueError(f"{len(problems)} proposed values do not trace to clean vanilla, e.g. {problems[0]['classname']} {problems[0]['path']}")
    return baseline


def tests_config(addons, build_id):
    names = [f"{PREFIX}_{name}" for name in addons]
    return "\n".join(["// A3 Balance test harness: config checks, damage test and the one-line session launcher.",
                      "class CfgPatches", "{", f"    class {TESTS}", "    {", '        name = "A3 Balance: tests";',
                      '        author = "A3 Balance";', "        requiredVersion = 2.18;",
                      "        requiredAddons[] = " + literal(names) + ";", "        units[] = {};", "        weapons[] = {};",
                      f"        buildId = {literal(build_id)};", "    };", "};", ""])


def build(root, destination=None):
    destination = destination or root / "balance-pilot"
    if destination.exists():
        raise ValueError(f"{destination.name} already exists; refusing to overwrite a reviewable build")
    changes = json.loads((root / "proposal/change_ledger.json").read_text(encoding="utf-8"))
    baseline = gate(root, changes)
    addons, checks, patch = build_patch(root)
    # Read the finished files as the engine will; no existing class may change parent.
    model = bound_model(root / "validation/remaining/full/snapshot.sqlite")
    moved = {name: predict(model, addon["config"]) for name, addon in addons.items()}
    if any(moved.values()):
        raise ValueError(f"The patch would change parent classes: { {k: v[:3] for k, v in moved.items() if v} }")
    build_id = hashlib.sha256(json.dumps([baseline["capture_sha256"], {n: a["hash"] for n, a in addons.items()}, checks],
                                         sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    template = (root / "verify_balance_pilot.template.sqf").read_text()
    expected = sqf([[f"{PREFIX}_{name}", addon["hash"]] for name, addon in addons.items()])
    parts = split(checks)
    manifest = {"build_id": build_id, "status": "built locally; NOT in-game validated", "clean_capture_sha256": baseline["capture_sha256"],
                "changed_fields": len(changes),
                "by_kind": {kind: {"target_classes": len({e["classname"].lower() for e in changes if e["kind"] == kind}), "changed_fields": n}
                            for kind, n in Counter(e["kind"] for e in changes).items()},
                "addons": {name: {"hash": a["hash"], "required_addons": a["required_addons"], "writes": a["writes"]} for name, a in addons.items()},
                "patch": patch, "checked_classes": len(checks), "verified_fields_expected": sum(count(c[3]) for c in checks),
                "loaded_references": [list(key) + [source] for key, source in LOADED_REFERENCE.items()],
                "numeric_tolerance": "max(1e-6, abs(expected)*1e-6)", "parts": []}
    scripts = []
    for number, part in enumerate(parts, 1):
        script = (template.replace("__BUILD_ID__", build_id).replace("__PART__", str(number)).replace("__PARTS__", str(len(parts)))
                  .replace("__ADDONS__", expected).replace("__CHECKS__", sqf(part)))
        scripts.append(script)
        manifest["parts"].append({"part": number, "script": f"verify_part{number}.sqf", "classes": len(part),
                                  "fields": sum(count(check[3]) for check in part), "sha256": hashlib.sha256(script.encode()).hexdigest()})
    # The session scripts travel inside the tests addon, so one console line runs every check and the damage test.
    acceptance = json.loads((root / "validation/acceptance-test/manifest.json").read_text(encoding="utf-8"))
    acceptance_script = (root / "validation/acceptance-test" / acceptance["script"]["file"]).read_bytes()
    if hashlib.sha256(acceptance_script).hexdigest() != acceptance["script"]["sha256"]:
        raise ValueError("Acceptance test script differs from its manifest; rerun prepare_acceptance_test.py")
    launcher = (root / "run_pilot_session.template.sqf").read_text().replace("__PARTS__", str(len(parts))).encode("utf-8")
    tests = [("config.cpp", tests_config(addons, build_id).encode())]
    tests += [(f"tests\\verify_part{n}.sqf", s.encode("utf-8")) for n, s in enumerate(scripts, 1)]
    tests += [("tests\\acceptance_test.sqf", acceptance_script), ("tests\\run.sqf", launcher)]
    pbos = {f"{PREFIX}_{name}": pack_files([("config.cpp", a["config"].encode("utf-8"))], f"{PREFIX}_{name}") for name, a in addons.items()}
    pbos[TESTS] = pack_files(tests, TESTS)
    manifest["session"] = {"console_line": SESSION_LINE, "acceptance_suite_id": acceptance["suite_id"],
                           "acceptance_trials": acceptance["expected_results"], "acceptance_blast_trials": acceptance["expected_blast_results"],
                           "packed_files": {name: hashlib.sha256(data).hexdigest() for name, data in tests}}
    manifest["pbo_sha256"] = {name: hashlib.sha256(data).hexdigest() for name, data in pbos.items()}
    manifest["config_sha256"] = {name: hashlib.sha256(a["config"].encode("utf-8")).hexdigest() for name, a in addons.items()}
    destination.mkdir()
    for name, addon in addons.items():
        source = destination / "source" / name
        source.mkdir(parents=True)
        (source / "config.cpp").write_text(addon["config"], encoding="utf-8", newline="\n")
    (destination / MOD / "addons").mkdir(parents=True)
    for name, data in pbos.items():
        (destination / MOD / "addons" / f"{name}.pbo").write_bytes(data)
    (destination / MOD / "mod.cpp").write_text('name = "A3 Balance Pilot";\ndescription = "Local test build of the balance patches, with their checks";\n', encoding="utf-8")
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
    print(json.dumps({key: result[key] for key in ("build_id", "by_kind", "checked_classes", "verified_fields_expected", "parts")}
                     | {"addons": {k: v["writes"] for k, v in result["addons"].items()}}, indent=2))
