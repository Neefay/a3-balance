"""Turn the change ledger into small per-mod config patches.

Usage: python build_patch.py [out_dir]   (default: patch/)
Reads proposal/change_ledger.json and the full-modset capture (validation/remaining/full/snapshot.sqlite).
Writes one addon per mod family, each `addons/<name>/config.cpp`, plus patch-manifest.json and the
in-game checks. Every addon:
  - changes only the values in the ledger, at the class that defines them, so inheritance carries them;
  - reopens each class with the parent it already has and declares only what its values need;
  - requires just that mod (its load-order addon where it has one) and skips itself when the mod is absent.
The whole modset is re-simulated with the patch before anything is written; see config_model.py.
"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

from build_helmet_pilot import literal
from config_model import infer_bindings, load
from emit_patch import PatchFile
from plan_patch import free, plan
from wearable_targets import BOOLEAN_TEXT, constant

PREFIX = "a3bal"
REQUIRED_VERSION = 2.18
# Addon-name prefix -> (addon name, load-order addon that pulls in the whole mod, or None)
FAMILIES = [
    ("rhsusf_", "rhs_usaf", "rhsusf_main_loadorder"), ("rhsgref_", "rhs_gref", "rhsgref_main_loadorder"),
    ("rhssaf_", "rhs_saf", "rhssaf_main_loadorder"), ("rhs_", "rhs_afrf", "rhs_main_loadorder"),
    ("uk3cb_baf_", "3cb_baf", None), ("uk3cb_", "3cb_factions", None), ("brm_", "broma", None),
    ("simc_", "sns", None), ("sns_", "sns_headgear", None), ("ron_", "ron", None),
]
VANILLA = ("a3_", "a3data", "core")


def family(addon):
    lower = addon.lower()
    for prefix, name, marker in FAMILIES:
        if lower.startswith(prefix):
            return name, marker
    if lower.startswith(VANILLA):
        return "vanilla", None
    return re.sub(r"[^a-z0-9]+", "_", lower).strip("_"), None


def comparable(value):
    """Ledger 'old' values evaluate mod text ("22+ 3", "true"); compare like with like."""
    if isinstance(value, str):
        if value.strip().lower() in BOOLEAN_TEXT:
            return BOOLEAN_TEXT[value.strip().lower()]
        evaluated = constant(value)
        return evaluated if evaluated is not None else value
    return value


def load_edits(ledger, model):
    edits, names, stale = {}, {}, []
    for edit in ledger:
        key = (edit["section"], edit["classname"].lower(), tuple(p.lower() for p in edit["path"]))
        if (key[0], key[1]) not in model.name:
            raise ValueError(f"Ledger class missing from the capture: {edit['section']} {edit['classname']}")
        observed = model.observed.get(key)
        if comparable(observed) != comparable(edit.get("old_text", edit["old"])):
            stale.append({"classname": edit["classname"], "path": edit["path"], "ledger": edit["old"], "captured": observed})
        edits[key] = edit["proposed"]
        names[key[2]] = tuple(edit["path"])
    if stale:
        raise ValueError(f"{len(stale)} ledger values no longer match the capture, e.g. {stale[:2]}; redraft the proposal")
    return edits, names


def partition(model, section, writes):
    """Split one mod's writes into as few files as keep every in-file parent binding right."""
    by_class = defaultdict(list)
    for cls, path, value in writes:
        by_class[cls].append((path, value))
    assign = dict.fromkeys(by_class, 0)
    for _ in range(16):
        files, moved = {}, False
        for index in sorted(set(assign.values())):
            f = PatchFile(model, section)
            for cls in sorted(c for c, i in assign.items() if i == index):
                for path, value in by_class[cls]:
                    node = model.top(section, cls)
                    for part in path[:-1]:
                        node = node[:2] + (node[2] + (part,),)
                    f.set(node, path[-1], model.values[(node, path[-1])][0], value)
            f.close()
            files[index] = f
            for problem in f.verify():
                owner = problem["node"][1]
                if assign.get(owner) == index:
                    assign[owner] = index + 1
                    moved = True
                elif owner not in assign:
                    raise ValueError(f"Unplaceable declaration in {section}: {problem}")
        if not moved:
            return [files[i] for i in sorted(files)]
    raise ValueError(f"{section}: in-file bindings did not converge")


def required(model, files):
    """Each mod's own addons for the classes a file reopens, as load-order addons where the mod has one."""
    needs = set()
    for f in files:
        for cls in f.classes():
            sources = model.sources.get((f.section, cls), [])
            if not sources:
                continue
            own, marker = family(sources[0])
            if marker:
                needs.add(marker)
            elif own == "vanilla":
                needs.add(sources[0])
            else:
                needs.update(s for s in sources if family(s)[0] == own)
    return sorted(needs, key=str.lower)


def checks_for(model, edits, placements, files_by_addon, names):
    """In-game checks: every class whose checked value could move, with its ancestry and expected values."""
    paths = defaultdict(set)
    for section, _, path in edits:
        paths[section].add(path)
    classes = set()
    for f in (f for files in files_by_addon.values() for f in files):
        classes.update((f.section, cls) for cls in f.classes())
    written_owners = {(section, cls) for section, cls, _ in placements}
    for (section, cls, path) in model.observed:
        if path in paths[section] and not free(model, section, cls):
            found = model.resolve(section, model.name[(section, cls)], path)
            if (section, cls, path) in edits or (found and (section, found[0][1]) in written_owners):
                classes.add((section, cls))
    checks = []
    for section, cls in sorted(classes):
        if free(model, section, cls):
            continue
        tree = {}
        for (s, c, path), _ in model.observed.items():
            if s != section or c != cls or path == ("scope",):
                continue
            value = model.value(section, model.name[(s, c)], path)
            node = tree
            spelled = names.get(path) or path
            for part in spelled[:-1]:
                node = node.setdefault(part, {})
            node[spelled[-1]] = value
        ancestry, parent = [model.name[(section, cls)]], model.parent[(section, cls)]
        while parent:
            ancestry.append(model.name.get((section, parent.lower()), model.parent_names.get(parent.lower(), parent)))
            parent = model.parent.get((section, parent.lower()), "")
        checks.append([section, model.name[(section, cls)], ancestry, nodes(tree)])
    return checks


def nodes(tree):
    out = []
    for key, value in tree.items():
        if isinstance(value, dict):
            out.append([key, "class", nodes(value)])
        else:
            out.append([key, "text" if isinstance(value, str) else "number", value])
    return out


def header(addon, needs, body_hash):
    return ["class CfgPatches", "{", f"    class {PREFIX}_{addon}", "    {",
            '        name = "A3 Balance: ' + addon.replace("_", " ") + '";', '        author = "A3 Balance";',
            f"        requiredVersion = {REQUIRED_VERSION};",
            "        requiredAddons[] = " + literal(needs) + ";",
            "        skipWhenMissingDependencies = 1;", "        units[] = {};", "        weapons[] = {};",
            f'        a3bal_hash = "{body_hash}";', "    };", "};"]


def build(root, snapshot=None):
    snapshot = snapshot or root / "validation/remaining/full/snapshot.sqlite"
    sys.setrecursionlimit(20000)
    model = load(snapshot)
    unexplained = infer_bindings(model)
    if unexplained:
        raise ValueError(f"The config model does not reproduce {len(unexplained)} captured values, e.g. {unexplained[:2]}")
    inferred = dict(model.bound)
    ledger = json.loads((root / "proposal/change_ledger.json").read_text(encoding="utf-8"))
    edits, names = load_edits(ledger, model)
    placements, report = plan(model, edits, names)
    by_addon = defaultdict(lambda: defaultdict(list))
    for (section, cls, path), value in placements.items():
        addon = family(model.sources[(section, cls)][0])[0]
        by_addon[addon][section].append((cls, path, value))
    files_by_addon, addons = {}, {}
    for addon in sorted(by_addon):
        sections = by_addon[addon]
        parts = defaultdict(list)
        for section in ("CfgAmmo", "CfgWeapons", "CfgVehicles"):
            for index, f in enumerate(partition(model, section, sections.get(section, []))):
                parts[index].append(f)
        for index, files in parts.items():
            name = addon if index == 0 else f"{addon}_{index + 1}"
            body = [line for f in files for line in f.render()]
            body_text = "\n".join(body) + "\n"
            digest = hashlib.sha256(body_text.encode()).hexdigest()
            needs = required(model, files)
            text = "\n".join([f"// A3 Balance: {addon.replace('_', ' ')} values on the vanilla ladder. Generated by tools/build_patch.py."]
                             + header(name, needs, digest)) + "\n" + body_text
            files_by_addon[name] = files
            addons[name] = {"config": text, "required_addons": needs, "hash": digest,
                            "writes": sum(len(f.values.get(n, {})) for f in files for n in f.values),
                            "classes": sorted({model.name[(f.section, c)] for f in files for c in f.classes() if (f.section, c) in model.name})}
    checks = checks_for(model, edits, placements, files_by_addon, names)
    cross = defaultdict(set)
    for section, cls, _ in placements:
        own = family(model.sources[(section, cls)][0])[0]
        for source in model.sources[(section, cls)][1:]:
            if family(source)[0] not in (own, "vanilla"):
                cross[source].add(model.name[(section, cls)])
    manifest = {"edits": len(edits), "plan": report, "addons": {k: {kk: v[kk] for kk in ("required_addons", "hash", "writes")} for k, v in addons.items()},
                "bytes": sum(len(a["config"].encode()) for a in addons.values()), "checked_classes": len(checks),
                "inferred_parent_bindings": [[list(k), list(v)] for k, v in inferred.items()],
                "other_mods_also_editing_written_classes": {k: len(v) for k, v in sorted(cross.items())}}
    return addons, checks, manifest


def write(out, addons, checks, manifest):
    if out.exists():
        raise ValueError(f"{out} already exists; refusing to overwrite a reviewable build")
    for name, addon in addons.items():
        folder = out / "addons" / name
        folder.mkdir(parents=True)
        (folder / "config.cpp").write_text(addon["config"], encoding="utf-8", newline="\n")
    (out / "patch-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (out / "expected-config.json").write_text(json.dumps(checks, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    out = root / (sys.argv[1] if len(sys.argv) > 1 else "patch")
    addons, checks, manifest = build(root)
    write(out, addons, checks, manifest)
    print(json.dumps({k: manifest[k] for k in ("edits", "plan", "bytes", "checked_classes")} | {"addons": {k: v["writes"] for k, v in manifest["addons"].items()}}, indent=2))
