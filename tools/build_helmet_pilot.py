"""Build a local, unsigned config-only helmet pilot after the clean reference gate."""
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import struct

from compare_clean_baseline import compare
from extract_rpt import get

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def identifier(name):
    if not IDENTIFIER.fullmatch(name):
        raise ValueError(f"Unsafe config identifier: {name!r}")
    return name


def literal(value):
    if isinstance(value, str):
        if any(c in value for c in "\x00\r\n"):
            raise ValueError("Control character in config string")
        return '"' + value.replace('"', '""') + '"'
    if type(value) in (int, float) and math.isfinite(value):
        return repr(value)
    if isinstance(value, list):
        return "{" + ",".join(literal(v) for v in value) + "}"
    raise ValueError(f"Unsupported config value: {value!r}")


def render_properties(props, indent="        "):
    lines = []
    for name, value in props.items():
        if name == "$parent":
            continue
        identifier(name)
        if isinstance(value, dict):
            lines.append(f"{indent}class {name}\n{indent}{{")
            lines.extend(render_properties(value, indent + "    "))
            lines.append(indent + "};")
        else:
            suffix = "[]" if isinstance(value, list) else ""
            lines.append(f"{indent}{name}{suffix} = {literal(value)};")
    return lines


def verification_fields(props, path=()):
    for name, value in props.items():
        if name == "$parent":
            continue
        current = path + (name,)
        if isinstance(value, dict):
            yield [list(current), "class", []]
            yield from verification_fields(value, current)
        else:
            kind = "array" if isinstance(value, list) else "text" if isinstance(value, str) else "number"
            yield [list(current), kind, value]


def pack_files(files, prefix):
    # Uncompressed entries in order, deterministic header, standard SHA-1 trailer.
    header = b"\0" + struct.pack("<5I", 0x56657273, 0, 0, 0, 0)
    header += b"prefix\0" + identifier(prefix).encode("ascii") + b"\0\0"
    for name, data in files:
        header += name.encode("ascii") + b"\0" + struct.pack("<5I", 0, len(data), 0, 0, len(data))
    body = header + b"\0" * 21 + b"".join(data for _, data in files)
    return body + b"\0" + hashlib.sha1(body).digest()


def pack_pbo(config, prefix="a3bal_helmets_pilot"):
    return pack_files([("config.cpp", config)], prefix)


def make_plan(records, changes, baseline):
    if not baseline["helmet_baseline_ready"]:
        raise ValueError("Clean helmet reference comparison has not passed")
    lookup = {row["classname"].lower(): row for row in records if row["section"] == "CfgWeapons"}
    patches = {row["classname"].lower() for row in records if row["section"] == "CfgPatches"}
    edits = [row for row in changes if row["kind"] == "headgear"]
    if not edits or any(row["section"] != "CfgWeapons" for row in edits):
        raise ValueError("Invalid helmet-only edit scope")
    targeted = {row["classname"].lower() for row in edits}
    affected = {name for name, row in lookup.items() if name in targeted or any(parent.lower() in targeted for parent in row["ancestry"][1:])}
    expected = {name: copy.deepcopy(lookup[name]["properties"]) for name in affected}
    for edit in edits:
        if len(edit["path"]) != 4 or edit["path"][0].lower() != "iteminfo" or edit["path"][-1].lower() not in {"armor", "passthrough"}:
            raise ValueError("Helmet edit escapes the selected protection scope")
        node = expected[edit["classname"].lower()]
        for key in edit["path"][:-1]:
            node = node[key]
        if node[edit["path"][-1]] != edit.get("old_text", edit["old"]):
            raise ValueError("Helmet proposal no longer matches observed input")
        node[edit["path"][-1]] = edit["proposed"]
    # shortcut: materialize complete observed ItemInfo to preserve undeclared nested fields;
    # regenerate for any preset/mod update, and verify all effective fields in-game.
    ordered, visiting, visited = [], set(), set()
    def visit(name):
        if name in visited:
            return
        if name in visiting or name not in lookup:
            raise ValueError(f"Missing/cyclic weapon ancestry: {name}")
        visiting.add(name)
        row = lookup[name]
        identifier(row["classname"])
        if len(row["ancestry"]) > 1:
            visit(row["ancestry"][1].lower())
        visiting.remove(name)
        visited.add(name)
        ordered.append(name)
    for name in sorted(affected):
        visit(name)
    dependencies = sorted({addon for name in ordered for addon in lookup[name]["sourceAddons"]} | {"A3_Characters_F"})
    if any(name.lower() not in patches for name in dependencies):
        raise ValueError("A required addon is absent from the observed CfgPatches snapshot")
    checks = [[lookup[name]["classname"], lookup[name]["ancestry"], list(verification_fields(expected[name]))] for name in sorted(affected)]
    build_id = hashlib.sha256(json.dumps([baseline["capture_sha256"], edits, checks, dependencies], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    lines = ["// Helmet-only local pilot. Full-preset snapshot; see the accompanying manifest.", "class CfgPatches", "{", "    class a3bal_helmets_pilot", "    {",
             '        name = "A3 Balance Helmets Pilot";', '        author = "Local balance project";',
             "        requiredVersion = 2.22;", "        requiredAddons[] = " + literal(dependencies) + ";",
             "        units[] = {};", "        weapons[] = {};", "        buildId = " + literal(build_id) + ";", "    };", "};", "class CfgWeapons", "{", "    class HeadgearItem;"]
    for name in ordered:
        row = lookup[name]
        parent = ": " + identifier(row["ancestry"][1]) if len(row["ancestry"]) > 1 else ""
        if name not in affected:
            if isinstance(get(row["properties"], "ItemInfo"), dict):
                lines += [f'    class {row["classname"]}{parent} {{ class ItemInfo; }};']
            else:
                lines += [f'    class {row["classname"]}{parent} {{}};' if parent else f'    class {row["classname"]};']
            continue
        info = get(expected[name], "ItemInfo")
        if not isinstance(info, dict) or info.get("$parent") not in {"ItemInfo", "HeadgearItem"}:
            raise ValueError("Unsupported ItemInfo inheritance in pilot")
        lines += [f'    class {row["classname"]}{parent}', "    {", f'        class ItemInfo: {info["$parent"]}', "        {"]
        lines.extend(render_properties(info, "            "))
        lines += ["        };", "    };"]
    lines += ["};", ""]
    manifest = {"build_id": build_id, "status": "built locally; NOT in-game validated", "scope": "helmets only",
                "clean_capture_sha256": baseline["capture_sha256"], "target_classes": len(targeted),
                "preserved_descendant_classes": len(affected - targeted), "materialized_iteminfo_classes": len(affected),
                "changed_fields": len(edits), "verified_fields_expected": sum(len(c[2]) for c in checks),
                "required_addons": dependencies, "target_classnames": [lookup[name]["classname"] for name in sorted(targeted)],
                "preserved_classnames": [lookup[name]["classname"] for name in sorted(affected-targeted)],
                "numeric_tolerance": "max(1e-6, abs(expected)*1e-6)",
                "limitation": "Snapshot materializes ItemInfo; use only with the original full preset and regenerate after updates."}
    return "\n".join(lines), checks, manifest


def build(root, destination=None):
    destination = destination or root / "helmet-pilot"
    if destination.exists():
        raise ValueError("helmet-pilot already exists; refusing to overwrite a reviewable build")
    baseline = compare(root)
    with (root / "data-recovered/configs.relevant.jsonl").open(encoding="utf-8") as stream:
        records = [json.loads(line) for line in stream]
    changes = json.loads((root / "proposal/change_ledger.json").read_text())
    config, checks, manifest = make_plan(records, changes, baseline)
    config_bytes = config.encode("utf-8")
    archive = pack_pbo(config_bytes)
    template = (root / "verify_helmet_pilot.template.sqf").read_text()
    # SQF array literals use doubled quotes, not JSON backslash escapes.
    def sqf(value):
        if isinstance(value, list):
            return "[" + ",".join(sqf(v) for v in value) + "]"
        return literal(value)
    script = template.replace("__BUILD_ID__", manifest["build_id"]).replace("__CHECKS__", sqf(checks))
    if len(script) >= 9000000:
        raise ValueError("Verification script exceeds the safe clipboard/console size; split the verification before release")
    manifest.update(pbo_sha256=hashlib.sha256(archive).hexdigest(), config_sha256=hashlib.sha256(config_bytes).hexdigest(),
                    verification_script_sha256=hashlib.sha256(script.encode()).hexdigest(),
                    source_export_sha256=hashlib.sha256((root / "data-recovered/configs.relevant.jsonl").read_bytes()).hexdigest())
    destination.mkdir()
    source = destination / "source/a3bal_helmets_pilot"
    source.mkdir(parents=True)
    (source / "config.cpp").write_bytes(config_bytes)
    mod = destination / "@A3Balance_Helmets_Pilot"
    (mod / "addons").mkdir(parents=True)
    (mod / "addons/a3bal_helmets_pilot.pbo").write_bytes(archive)
    (mod / "mod.cpp").write_text('name = "A3 Balance Helmets Pilot";\ndescription = "Local helmet-only config and inheritance pilot";\n', encoding="utf-8")
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (destination / "expected-config.json").write_text(json.dumps(checks, ensure_ascii=False), encoding="utf-8")
    (destination / "verify_helmet_pilot.sqf").write_text(script, encoding="utf-8", newline="")
    return manifest


if __name__ == "__main__":
    import sys
    root = Path(__file__).resolve().parent
    result = build(root, root / sys.argv[1] if len(sys.argv) > 1 else None)
    print(json.dumps({key: result[key] for key in ("build_id", "target_classes", "preserved_descendant_classes", "changed_fields", "verified_fields_expected", "pbo_sha256")}, indent=2))
