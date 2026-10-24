"""Build a wearable spreadsheet and coverage report from recovered configs."""
from collections import Counter
import csv
import json
from pathlib import Path
import sys

from extract_rpt import canonical, get


def inventory(directory):
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    if summary["status"] not in ("complete", "partial"):
        raise ValueError("Extraction has not finished")
    with (directory / "wearables.jsonl").open(encoding="utf-8") as stream:
        gear = [json.loads(line) for line in stream]
    unit_references = {str(get(get(row["properties"], "ItemInfo", {}), "uniformClass", "")).lower()
                       for row in gear if row["kind"] == "uniform"}
    units = {}
    simulation_counts = Counter()
    scoped_gear = Counter()
    with (directory / "configs.relevant.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["section"] == "CfgVehicles" and row["classname"].lower() in unit_references:
                units[row["classname"].lower()] = row["properties"]
            elif row["section"] == "CfgAmmo":
                simulation_counts[str(get(row["properties"], "simulation", "<missing>"))] += 1
    unresolved = {}
    with (directory / "wearables.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["classname", "kind", "scope", "scopeArsenal", "displayName", "sourceAddons",
                         "mass", "containerClass", "uniformClass", "linkedUnitRecovered",
                         "itemArmor", "itemPassThrough", "itemProtection", "linkedUnitArmor",
                         "linkedUnitArmorStructural", "linkedUnitHitPoints"])
        for row in gear:
            props = row["properties"]
            kind = row["kind"]
            info = get(props, "ItemInfo", {}) if kind != "glasses" else props
            reference = get(info, "uniformClass", "")
            unit = units.get(reference.lower()) if reference else None
            if kind == "uniform" and reference and unit is None:
                unresolved.setdefault(reference, []).append(row["classname"])
            scope = get(props, "scope")
            scoped_gear[f"{kind}:scope={scope}"] += 1
            writer.writerow([row["classname"], kind, scope, get(props, "scopeArsenal"),
                             get(props, "displayName"), canonical(row["sourceAddons"]),
                             get(info, "mass"), get(info, "containerClass"), reference,
                             unit is not None if reference else "",
                             get(info, "armor"), get(info, "passThrough"),
                             canonical(get(info, "HitpointsProtectionInfo", {})),
                             get(unit, "armor") if unit is not None else "",
                             get(unit, "armorStructural") if unit is not None else "",
                             canonical(get(unit, "HitPoints", {})) if unit is not None else ""])
    result = {"extraction_status": summary["status"],
              "recovered_sections": summary["sections"],
              "missing_by_section": summary.get("missing_by_section", {}),
              "wearable_scope_counts": dict(sorted(scoped_gear.items())),
              "ammo_simulations": dict(simulation_counts.most_common()),
              "unresolved_uniform_references": unresolved,
              "note": "Hidden/base classes are included. Missing values are not treated as zero. "
                      "An unresolved unit may be absent from the export or from the loaded config."}
    (directory / "inventory.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(inventory(Path(sys.argv[1])), ensure_ascii=False, indent=2))
