"""Stream A3EQ log chunks into a lossless archive and compact config datasets."""
import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re
import time


FRAME = re.compile(rb"A3EQ\|([^|\r\n]+)\|(\d+)\|(\d+)\|(\d+)\|(\[[0-9, ]*\])\|END")
SQF_STRING = re.compile(r'"(?:[^"\x00]|"")*"')


def parse_sqf(source):
    # SQF doubles quotes and treats backslashes literally; JSON does neither.
    translated = SQF_STRING.sub(
        lambda m: json.dumps(m[0][1:-1].replace('""', '"')), source
    )
    return json.loads(translated)


def unpack(entries):
    result = {}
    for name, kind, value in entries:
        if kind == "class":
            parent, children = value
            result[name] = {"$parent": parent, **unpack(children)}
        elif kind in ("number", "text", "array"):
            result[name] = value
        else:
            raise ValueError(f"Unknown property type: {kind!r}")
    return result


def get(mapping, name, default=None):
    return next((v for k, v in mapping.items() if k.lower() == name.lower()), default)


WEAPON_FIELDS = set("""
    displayname scope scopearsenal type baseweapon magazines magazinewell muzzles
    modes initspeed mass inertia dexterity dispersion recoil recoilprone
    magazinesreloadtime magazinereloadtime reloadaction reloadtime
    maxrange maxrangeprobab midrange midrangeprobab minrange minrangeprobab
    multiplier burst autofire aiRateOfFire aiRateOfFireDistance
    soundtypeindex ammo damage armor passthrough hitpoints uniformclass
    containerclass maximumload hiddenselections
""".lower().split())
VEHICLE_FIELDS = set("""
    displayname scope scopearsenal uniformclass model armor armorstructural
    explosionShielding damageresistance impactdamagemultiplier
    sensitivity sensitivityear armorhead armorhands armorlegs armorbody
    passthrough minimalhit mass maximumload transportmaxmagazines
    transportmaxweapons transportmaxbackpacks isbackpack
""".lower().split())
MAGAZINE_FIELDS = set("""
    displayname scope scopearsenal type ammo count initspeed mass
    tracersevery lastroundstracer model special magazinegroup
""".lower().split())


def weapon_properties(props):
    nested = {"iteminfo", "hitpoints", "hitpointsprotectioninfo"}
    for field in ("muzzles", "modes"):
        nested.update(str(v).lower() for v in get(props, field, []) if isinstance(v, str))
    result = {}
    for key, value in props.items():
        name = key.lower()
        if isinstance(value, dict):
            if name in ("iteminfo", "hitpoints", "hitpointsprotectioninfo"):
                result[key] = value
            elif name == "weaponslotsinfo":
                result[key] = {k: v for k, v in value.items() if k.lower() in ("mass", "$parent")}
            elif name in nested:
                result[key] = weapon_properties(value)
        elif name in WEAPON_FIELDS or name.startswith(("ace_", "rhs_")) or name == "$parent":
            result[key] = value
    return result


def compact(section, props):
    if section == "CfgWeapons":
        return weapon_properties(props)
    if section == "CfgVehicles":
        return {k: v for k, v in props.items()
                if k.lower() in VEHICLE_FIELDS or k.lower() == "hitpoints"
                or k.lower().startswith(("ace_", "rhs_"))}
    if section == "CfgMagazines":
        return {k: v for k, v in props.items()
                if k.lower() in MAGAZINE_FIELDS or k.lower().startswith(("ace_", "rhs_"))}
    # Ammo keeps every scalar/array field, including mod-specific attributes.
    return {k: v for k, v in props.items() if not isinstance(v, dict)}


def wearable_kind(section, ancestry, props):
    if section == "CfgGlasses":
        return "glasses"
    if section != "CfgWeapons":
        return None
    info = get(props, "ItemInfo", {})
    item_type = get(info, "type")
    kind = {605: "headgear", 701: "vest", 801: "uniform"}.get(item_type)
    if kind:
        return kind
    names = {name.lower() for name in ancestry}
    if "uniform_base" in names:
        return "uniform"
    if names.intersection({"vest_camo_base", "vest_nocamo_base"}):
        return "vest"
    return None


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def extract(source, output, selected_run=None, salvage=False):
    output.mkdir(parents=True, exist_ok=False)
    report = {"source": str(source), "source_bytes": source.stat().st_size,
              "status": "incomplete", "sections": {}, "wearables": {}}
    counts, gear_counts = Counter(), Counter()
    profiles = {}
    sequence = 0
    next_part = 0
    part_count = None
    pieces = []
    ended = False
    discarded_record = None
    missing = set()
    issues = []
    decoded = 0
    matched = 0
    consumed = 0
    last_progress = 0
    start = time.monotonic()

    try:
        with source.open("rb", buffering=4 * 1024 * 1024) as rpt, \
             gzip.open(output / "configs.full.jsonl.gz", "wt", encoding="utf-8", compresslevel=1) as archive, \
             (output / "configs.relevant.jsonl").open("w", encoding="utf-8") as relevant, \
             (output / "wearables.jsonl").open("w", encoding="utf-8") as wearables, \
             (output / "ammo.csv").open("w", encoding="utf-8", newline="") as ammo_file:
            ammo_writer = csv.writer(ammo_file)
            ammo_writer.writerow(["classname", "displayName", "sourceAddons", "simulation",
                                  "hit", "caliber", "typicalSpeed", "airFriction",
                                  "indirectHit", "indirectHitRange", "explosive"])
            for line_number, line in enumerate(rpt, 1):
                consumed += len(line)
                if consumed - last_progress >= 128 * 1024 * 1024:
                    elapsed = time.monotonic() - start
                    print(f"{consumed / report['source_bytes']:.1%} | {sequence:,} records | "
                          f"{consumed / 1024**2 / max(elapsed, .001):.1f} MiB/s", flush=True)
                    last_progress = consumed
                if b"A3EQ|" not in line:
                    continue
                match = FRAME.search(line)
                if not match:
                    if salvage:
                        issues.append({"line": line_number, "error": "Malformed export frame"})
                        continue
                    raise ValueError(f"Malformed or truncated export frame at log line {line_number}")
                run = match[1].decode("ascii")
                if selected_run is None:
                    selected_run = run
                    report["run"] = run
                if run != selected_run:
                    continue
                matched += 1
                if ended:
                    raise ValueError("More frames for this run after END")
                record, part, total = map(int, (match[2], match[3], match[4]))
                if record == discarded_record:
                    continue
                if record != sequence or part != next_part or total < 1:
                    message = (f"Missing, duplicate, or reordered chunk at line {line_number}: "
                               f"expected record {sequence} part {next_part}; got {record}/{part}/{total}")
                    if not salvage or record < sequence or total < 1:
                        raise ValueError(message)
                    issue = {"line": line_number, "expected_record": sequence,
                             "expected_part": next_part, "next_record": record, "next_part": part}
                    prefix = "".join(pieces[:4])
                    identity = re.match(r'^\["(Cfg[^"\r\n]+)","([^"\r\n]+)"', prefix)
                    if identity:
                        issue["incomplete_class"] = list(identity.groups())
                    issues.append(issue)
                    missing.update(range(sequence, record))
                    pieces.clear()
                    next_part = 0
                    sequence = record
                    if part != 0:
                        missing.add(record)
                        discarded_record = record
                        sequence = record + 1
                        continue
                if part == 0:
                    part_count = total
                if total != part_count:
                    raise ValueError(f"Chunk count changed at line {line_number}")
                codes = json.loads(match[5])
                if len(codes) > 80 or not codes or (part < total - 1 and len(codes) != 80):
                    raise ValueError(f"Invalid chunk length at line {line_number}")
                pieces.append("".join(map(chr, codes)))
                next_part += 1
                if next_part != total:
                    continue
                raw = "".join(pieces)
                try:
                    data = parse_sqf(raw)
                except Exception as error:
                    (output / f"failed_record_{record}.sqf").write_text(raw, encoding="utf-8")
                    if not salvage:
                        raise
                    missing.add(record)
                    issues.append({"record": record, "parse_error": str(error)})
                    sequence += 1
                    pieces.clear()
                    next_part = 0
                    continue
                archive.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
                decoded += 1
                if sequence == 0:
                    if not (len(data) == 5 and data[:3] == ["BEGIN", "ARMA_EQUIPMENT_DUMP", 2]):
                        raise ValueError("Unexpected export header/schema")
                    report["header"] = data
                elif data[0] == "END":
                    expected = dict(data[1])
                    if data[2] != sequence or expected != dict(counts):
                        if not salvage or data[2] != sequence:
                            raise ValueError(f"END counts disagree: expected {expected}; decoded {dict(counts)}")
                        issues.append({"error": "END section counts differ from recovered counts"})
                    ended = True
                    report["footer"] = data
                    report["expected_sections"] = expected
                    report["missing_by_section"] = {k: n - counts[k] for k, n in expected.items() if n != counts[k]}
                else:
                    section, classname, ancestry, addons, entries = data
                    props = unpack(entries)
                    row = {"section": section, "classname": classname, "ancestry": ancestry,
                           "sourceAddons": addons, "properties": compact(section, props)}
                    relevant.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                    counts[section] += 1
                    if section == "CfgAmmo":
                        ammo_writer.writerow([classname, get(props, "displayName"), canonical(addons)] +
                            [get(props, field) for field in ["simulation", "hit", "caliber", "typicalSpeed",
                             "airFriction", "indirectHit", "indirectHitRange", "explosive"]])
                    kind = wearable_kind(section, ancestry, props)
                    if kind:
                        row["kind"] = kind
                        wearables.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                        gear_counts[kind] += 1
                        info = get(props, "ItemInfo", {})
                        # These are matching exported protection fields, not proven equivalent items.
                        protection = {"kind": kind, "fields": {k: v for k, v in info.items()
                            if k.lower() in ("armor", "passthrough", "explosionshielding", "hitpointsprotectioninfo")}}
                        if kind == "uniform":
                            protection["uniformClass"] = get(info, "uniformClass")
                        if kind == "glasses":
                            protection["fields"] = {k: v for k, v in props.items()
                                if k.lower() in ("armor", "passthrough", "explosionshielding", "hitpointsprotectioninfo")}
                        key = canonical(protection)
                        group = profiles.setdefault(key, {"profile": protection, "classes": []})
                        group["classes"].append(classname)
                sequence += 1
                pieces.clear()
                next_part = 0
            if not ended or pieces:
                raise ValueError("Export is incomplete: missing END record or unfinished chunks")
        profile_rows = [dict(profileId=hashlib.sha256(key.encode()).hexdigest()[:16], **value)
                        for key, value in profiles.items()]
        (output / "wearable_protection_groups.json").write_text(
            json.dumps(profile_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        report["status"] = "partial" if issues or missing else "complete"
        report["protection_groups"] = len(profile_rows)
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        ranges = []
        for number in sorted(missing):
            if ranges and number == ranges[-1][1] + 1:
                ranges[-1][1] = number
            else:
                ranges.append([number, number])
        report.update(sections=dict(counts), wearables=dict(gear_counts), issues=issues,
                      missing_records=len(missing), missing_record_ranges=ranges,
                      decoded_records=decoded, matched_chunks=matched,
                      elapsed_seconds=round(time.monotonic() - start, 2))
        report["files"] = {p.name: p.stat().st_size for p in output.iterdir() if p.is_file()}
        (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rpt", type=Path)
    parser.add_argument("output", type=Path, help="New output directory; existing directories are refused")
    parser.add_argument("--run", help="Select a run ID; defaults to the first encountered run")
    parser.add_argument("--salvage", action="store_true", help="Skip incomplete records and report every gap")
    args = parser.parse_args()
    summary = extract(args.rpt, args.output, args.run, args.salvage)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
