"""Compare the validated clean capture to observed data without changing either."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from extract_rpt import get

# Second, broader clean capture (vanilla-only batch, import_remaining_capture.py): covers anchors the first lacks.
CLEAN_SNAPSHOT = Path("validation/remaining/clean/snapshot.sqlite")


def snapshot_checks(root, names):
    """Head-region armor/passThrough of each anchor in the clean snapshot against the observed export."""
    meta_path = root / CLEAN_SNAPSHOT
    if not names:
        return [], []
    checks, drift = [], []
    with closing(sqlite3.connect(f"file:{meta_path}?mode=ro", uri=True)) as clean, closing(sqlite3.connect(root / "equipment.sqlite")) as db:
        mode = json.loads(clean.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()[0])
        mods = json.loads(clean.execute("SELECT value FROM metadata WHERE key='loaded_mods'").fetchone()[0])
        if mode != "clean" or any(row[2] is not True for row in mods):
            raise ValueError("Second clean capture has non-official mods")
        for name in names:
            observed = db.execute("SELECT properties_json FROM configs WHERE section='CfgWeapons' AND classname=?", (name,)).fetchone()
            if observed is None:
                raise ValueError(f"No observed reference class: CfgWeapons/{name}")
            for path, kind, value in clean.execute("SELECT path, kind, value FROM fields WHERE section='CfgWeapons' AND classname=? "
                                                   "AND path LIKE '[\"ItemInfo\",\"HitpointsProtectionInfo\",%'", (name,)):
                parts = json.loads(path)
                if parts[-1].lower() not in ("armor", "passthrough"):
                    continue
                old, present = json.loads(observed[0]), True
                for part in parts:
                    if not isinstance(old, dict) or not any(key.lower() == part.lower() for key in old):
                        present = False
                        break
                    old = get(old, part)
                row = {"section": "CfgWeapons", "classname": name, "path": parts, "observed_present": present,
                       "observed": old if present else None, "clean": json.loads(value) if kind == "number" else value}
                checks.append(row)
                if kind != "number" or not present or old != row["clean"]:
                    drift.append(row)
    return checks, drift


def compare(root):
    capture_path = root / "validation/clean-vanilla-capture.json"
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    manifest = json.loads((root / "validation/clean_capture_manifest.json").read_text())
    expected = {(section, name) for section, name, _ in manifest["requests"]}
    actual = {(row[1], row[2]) for row in capture["classes"]}
    if capture["manifest_sha256"] != manifest["requests_sha256"] or actual != expected:
        raise ValueError("Clean capture does not match the requested reference set")
    if not capture["loaded_mods"] or any(row[3] is not True for row in capture["loaded_mods"]):
        raise ValueError("Clean capture has non-official mods")
    anchors = json.loads((root / "proposal/anchors.json").read_text())
    helmets = {row["classname"] for row in anchors if row["kind"] == "headgear"}
    differences, matching, absent = [], 0, []
    with closing(sqlite3.connect(root / "equipment.sqlite")) as db:
        for _, section, name, path, kind, clean in capture["fields"]:
            result = db.execute("SELECT properties_json FROM configs WHERE section=? AND classname=?", (section, name)).fetchone()
            if result is None:
                raise ValueError(f"No observed reference class: {section}/{name}")
            old = json.loads(result[0])
            present = True
            for part in path:
                if not isinstance(old, dict) or not any(key.lower() == part.lower() for key in old):
                    present = False
                    break
                old = get(old, part)
            if not present:
                old = None
            if kind == "missing":
                absent.append({"section": section, "classname": name, "path": path, "observed_present": present, "observed": old})
            elif not present or old != clean:
                differences.append({"section": section, "classname": name, "path": path,
                                    "observed_present": present, "observed": old, "clean": clean})
            else:
                matching += 1
    helmet_drift = [row for row in differences + absent if row["section"] == "CfgWeapons" and row["classname"] in helmets]
    captured_helmets = {row[2] for row in capture["fields"] if row[1] == "CfgWeapons" and row[2] in helmets}
    extra_checks, extra_drift = snapshot_checks(root, sorted(helmets - captured_helmets))
    snapshot_helmets = {row["classname"] for row in extra_checks}
    report = {"run": capture["run"], "capture_sha256": hashlib.sha256(capture_path.read_bytes()).hexdigest(),
              "product_version": capture["product_version"], "classes": len(actual), "matching_fields": matching,
              "differences": differences, "clean_missing_fields": absent,
              "helmet_reference_classes": sorted(helmets), "helmet_reference_differences": helmet_drift + extra_drift,
              "helmet_snapshot_checks": extra_checks,
              "helmet_baseline_ready": bool(helmets) and not helmet_drift and not extra_drift and helmets == captured_helmets | snapshot_helmets,
              "future_ammo_reconciliation_required": any(row["section"] == "CfgAmmo" for row in differences)}
    (root / "validation/clean-baseline-comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = ["# Clean vanilla comparison", "", f'Capture run: `{capture["run"]}`. All {len(actual)} requested classes are present.',
             f'{matching} fields match the mod-loaded observations; {len(differences)} differ.',
             f"All {len(helmets)} helmet reference classes match ({len(captured_helmets)} in this capture, "
             f"{len(snapshot_helmets)} in the second clean capture `{CLEAN_SNAPSHOT.as_posix()}`). The helmet-only baseline gate passes.", "",
             "| Class | Field | Mod-loaded observation | Clean vanilla |", "|---|---|---:|---:|"]
    for row in differences:
        lines.append(f'| {row["classname"]} | {"/".join(row["path"])} | {row["observed"]} | {row["clean"]} |')
    lines += ["", "Drag (airFriction) is outside the terminal-field patch scope. The 7.62x54R",
              "reference speed is ACE ballistics' loaded value (835; clean 800); the ammunition",
              "ladder uses the loaded value, declared in build_balance_pilot.LOADED_REFERENCE",
              "and measured by the range test. No original observed value was overwritten by",
              "this comparison.", "",
              "This comparison validates the captured reference values, not the runtime behavior",
              "of a future PBO. Effective-config and inheritance verification remain required."]
    if not report["helmet_baseline_ready"]:
        lines[4] = "Helmet baseline gate is NOT ready; inspect the JSON differences."
    (root / "validation/CLEAN_BASELINE_COMPARISON.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = compare(Path(__file__).resolve().parent)
    print(json.dumps({key: result[key] for key in ("classes", "matching_fields", "helmet_baseline_ready", "future_ammo_reconciliation_required")}, indent=2))
