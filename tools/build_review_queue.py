"""Rank identity questions by public item count without assigning balance targets."""
from collections import defaultdict
import csv
import json
from pathlib import Path
import re

from draft_balance import head_entry, EXCLUDED
from extract_rpt import get


def family(row):
    name = row["classname"]
    text = name + " " + str(get(row["properties"], "displayName", ""))
    for label, pattern in (("LWH", r"(?:^|[_\s])lwh(?:[_\s]|$)"),
                           ("6B7-1M", r"6b7.?1m"), ("6B7", r"6b7"),
                           ("Mk6 / MkVI", r"mk6|mkvi(?!i)|mk vi(?!i)"),
                           ("Mk7 / MkVII", r"mk7|mkvii|mk vii"),
                           ("HGU-56/P", r"hgu.?56"), ("SPH-4 family", r"sph.?4"),
                           ("M97", r"(?:^|[_\s])m97(?:[_\s]|$)"),
                           ("Ballistic masks", r"ballistic.?mask"),
                           ("HSAT MkIII", r"hsat.*mkiii"), ("HSAT P-Type", r"hsat.*p.?type"),
                           ("MkIV", r"mkiv|mk iv"),
                           ("KKZ10", r"kkz10"), ("MD99 / M-99", r"md99|m.?99"),
                           ("Eagle vest", r"eagle"), ("Pilot vest", r"pilot"),
                           ("T/G Faust", r"faust|fauf")):
        if re.search(pattern, text, re.I):
            return label
    model = get(get(row["properties"], "ItemInfo", {}), "uniformModel", "")
    if model and model != "-":
        normalized = model.lower().replace("/", "\\").strip("\\").removesuffix(".p3d")
        return "Model family: " + normalized
    return "Class family: " + "_".join(name.split("_")[:2])


def build(root):
    proposal = root / "proposal"
    gear = {row["classname"].lower(): row for row in map(json.loads, (root / "data-recovered/wearables.jsonl").read_text(encoding="utf-8").splitlines())}
    targets = json.loads((proposal / "wearable_targets.json").read_text())
    with (proposal / "coverage.csv").open(encoding="utf-8-sig", newline="") as stream:
        coverage = {row["classname"].lower(): row for row in csv.DictReader(stream) if row["section"] == "CfgWeapons"}
    groups = defaultdict(list)
    for target in targets:
        # A ceiling cap only bounds an unknown item; its identity is still open.
        if target["kind"] != "vest" or target["status"] not in {"review_no_selected_vest_tier", "proposed_ceiling_cap"}:
            continue
        if target["role"] in {"explosive_specialist", "diving", "modular_carrier"}:
            continue
        row = gear[target["classname"].lower()]
        groups[("vest", family(row))].append(row)
    for lower, row in gear.items():
        if row["kind"] != "headgear" or coverage[lower]["status"] not in {"review_identity", "proposed_ceiling_cap"}:
            continue
        entry = head_entry(get(row["properties"], "ItemInfo", {}))
        armor = get(entry[2], "armor") if entry else None
        text = row["classname"] + " " + str(get(row["properties"], "displayName", ""))
        if type(armor) in (int, float) and armor > 0 and not EXCLUDED.search(text):
            groups[("headgear", family(row))].append(row)
    rows = []
    for (kind, label), members in groups.items():
        public = [row for row in members if get(row["properties"], "scope") == 2]
        if not public:
            continue
        rows.append({"kind": kind, "family": label, "item_count": len(public),
                     "all_scope_count": len(members),
                     "examples": [row["classname"] for row in public[:4]],
                     "display_examples": [get(row["properties"], "displayName", "") for row in public[:3]],
                     "classes": [row["classname"] for row in members],
                     "question": "Does this contain plates, soft armor, or no armor; is a light carrier positively identified?" if kind == "vest" else "What helmet construction and gameplay role does this family represent?"})
    rows.sort(key=lambda row: (-row["item_count"], row["kind"], row["family"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    (proposal / "unresolved_families.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    with (proposal / "unresolved_families.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["rank", "kind", "family", "item_count", "all_scope_count", "examples", "display_examples", "question", "classes"])
        writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in row.items()} for row in rows)
    lines = ["# Unresolved equipment families, ranked by public item count", "",
             "Counts are recovered classes with numeric scope 2, including cosmetic variants.",
             "They prioritize identification effort, not independent protection evidence.",
             "Name/model groups are review queues, not proof of identical construction.",
             "Explicitly deferred specialists, text-only questions, hidden-only groups, and",
             "families already assigned a tier are excluded from this identification queue.",
             "Items held under the v7 ceiling cap are still listed: the cap bounds them, it does not identify them.", "",
             "| Rank | Kind | Family / model group | Public items | Examples |", "|---:|---|---|---:|---|"]
    for row in rows:
        lines.append(f'| {row["rank"]} | {row["kind"]} | {row["family"]} | {row["item_count"]} | ' + "; ".join(f'`{name}`' for name in row["examples"]) + " |")
    lines += ["", "For vests, identify whether plates are actually present, whether protection is soft only,",
              "or whether the item is load-bearing only. A positively identified light plate carrier",
              "can receive the light tier; otherwise an identified plate carrier defaults to regular.",
              "Generic unknown vests are not assumed to contain plates.", "",
              "For helmets, identify construction and whether an ordinary or specialist role is intended.",
              "All member classnames and display examples are in unresolved_families.csv/json.", "",
              "## Ammunition identity backlog (separate counts)", "",
              "Projectile classes are not wearable item variants. Handheld-only use is classified from the",
              "full-preset capture (ammunition_handheld_usage.json). A cartridge is released whole, so one",
              "unidentified variant (review_variant_identity) blocks every round of that cartridge.", "",
              "| Identity disposition | Projectile classes | Examples |", "|---|---:|---|"]
    ammo = json.loads((proposal / "ammunition_mapping.json").read_text())
    for status in ("review_variant_identity", "review_cartridge_identity", "preserved_outside_scale",
                   "deferred_handheld_usage_proof", "deferred_cartridge_incomplete"):
        members = [row for row in ammo if row["status"] == status]
        lines.append(f'| {status} | {len(members)} | ' + "; ".join(f'`{row["classname"]}`' for row in members[:5]) + " |")
    lines += ["", "Use ammunition_mapping.csv for every identity and candidate target. Remaining rifle cartridges",
              "come before pistol/SMG. Specialized rounds follow the derived v7 ladder; subsonic rounds keep",
              "observed values. See AMMUNITION.md for the ladder and the cartridge release rule."]
    (proposal / "UNRESOLVED_FAMILIES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rows


if __name__ == "__main__":
    result = build(Path(__file__).resolve().parent)
    print(json.dumps([{k: row[k] for k in ("rank", "kind", "family", "item_count")} for row in result[:12]], indent=2))
