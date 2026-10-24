"""Stream bounded batch records into a NEW snapshot and queryable SQLite file.

No recovered dataset, proposal, or existing database is updated. Partial imports
are retained with a failed report and never reported as complete.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from extract_rpt import parse_sqf
from import_clean_capture import read_records
from import_helmet_verification import validate_pilot

PREFIX = re.compile(rb"A3BALBATCH\|([^|\r\n]+)\|")
FRAME = re.compile(rb"A3BALBATCH\|([^|\r\n]+)\|(\d+)\|(\d+)\|(\d+)\|(\[[0-9, ]*\])\|END")
SECTIONS = {"CfgWeapons", "CfgMagazines", "CfgMagazineWells", "CfgAmmo", "CfgVehicles", "CfgGlasses", "CfgPatches"}


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def iter_records(rpt, selected_run=None):
    """Keep only one decoded record in memory. Require ordered, complete frames."""
    identity = selected_run
    expected_record, expected_part = 1, 1
    total_parts = None
    chunks = []
    seen = False
    with rpt.open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            prefix = PREFIX.search(line)
            if not prefix:
                continue
            run = prefix[1].decode("ascii")
            if identity is None:
                identity = run
            if run != identity:
                if selected_run is None:
                    raise ValueError("Multiple batch runs: select one with --run")
                continue
            seen = True
            match = FRAME.search(line)
            if not match:
                raise ValueError(f"Truncated/malformed batch frame at RPT line {line_number}; rerun the batch")
            record, part, total = (int(match[i]) for i in (2, 3, 4))
            if record != expected_record or part != expected_part or not 1 <= part <= total <= 100000:
                raise ValueError(f"Missing, duplicate or out-of-order frame at RPT line {line_number}")
            if total_parts is not None and total_parts != total:
                raise ValueError("Inconsistent frame total")
            total_parts = total
            codes = json.loads(match[5])
            if not 1 <= len(codes) <= 96 or any(type(c) is not int or not 0 <= c <= 0x10FFFF for c in codes):
                raise ValueError("Invalid character-code frame")
            chunks.append("".join(chr(c) for c in codes))
            if part == total:
                payload = parse_sqf("".join(chunks))
                if not isinstance(payload, list) or not payload:
                    raise ValueError("Invalid record payload")
                yield identity, expected_record, payload
                expected_record += 1
                expected_part, total_parts, chunks = 1, None, []
            else:
                expected_part += 1
    if not seen or chunks:
        raise ValueError("No selected batch capture or incomplete final record")


def flatten(fields, prefix=()):
    seen = set()
    for name, node in fields:
        if not isinstance(name, str) or name.lower() in seen:
            raise ValueError("Invalid/duplicate config field")
        seen.add(name.lower())
        path = prefix + (name,)
        kind = node[0]
        if kind == "class" and len(node) == 4:
            yield path, kind, {"parent": node[1], "direct_names": node[2]}
            yield from flatten(node[3], path)
        elif kind in {"number", "text", "array", "missing"} and len(node) == 2:
            value = node[1]
            valid = ((kind == "number" and type(value) in (int, float)) or
                     (kind == "text" and isinstance(value, str)) or
                     (kind == "array" and isinstance(value, list)) or
                     (kind == "missing" and value == []))
            if not valid:
                raise ValueError("Config value disagrees with its type")
            yield path, kind, value
        else:
            raise ValueError("Invalid config node or recursion limit reached")


def schema(db):
    db.executescript("""
    CREATE TABLE configs(section TEXT, classname TEXT COLLATE NOCASE, source_addons TEXT,
      ancestry TEXT, direct_names TEXT, PRIMARY KEY(section,classname));
    CREATE TABLE fields(section TEXT, classname TEXT COLLATE NOCASE, path TEXT COLLATE NOCASE,
      kind TEXT, value TEXT, PRIMARY KEY(section,classname,path));
    CREATE TABLE weapon_magazines(weapon TEXT COLLATE NOCASE, muzzle TEXT COLLATE NOCASE,
      magazine TEXT COLLATE NOCASE, source TEXT, PRIMARY KEY(weapon,muzzle,magazine,source));
    CREATE TABLE muzzle_wells(weapon TEXT COLLATE NOCASE, muzzle TEXT COLLATE NOCASE,
      well TEXT COLLATE NOCASE, PRIMARY KEY(weapon,muzzle,well));
    CREATE TABLE mount_nodes(vehicle TEXT COLLATE NOCASE, path TEXT COLLATE NOCASE,
      PRIMARY KEY(vehicle,path));
    CREATE TABLE mounts(vehicle TEXT COLLATE NOCASE, path TEXT COLLATE NOCASE,
      kind TEXT, value TEXT COLLATE NOCASE, PRIMARY KEY(vehicle,path,kind,value));
    CREATE TABLE probes(section TEXT, classname TEXT COLLATE NOCASE, path TEXT COLLATE NOCASE,
      data TEXT, PRIMARY KEY(section,classname,path));
    CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
    CREATE INDEX fields_by_path ON fields(section,path);
    CREATE INDEX magazines_by_magazine ON weapon_magazines(magazine);
    CREATE INDEX mounts_by_value ON mounts(kind,value);
    CREATE VIEW magazine_ammo AS
      SELECT classname AS magazine, json_extract(value,'$') AS ammo FROM fields
      WHERE section='CfgMagazines' AND path='["ammo"]' AND kind='text';
    CREATE VIEW projectile_vehicle_magazines AS
      SELECT a.ammo, a.magazine, m.vehicle, m.path FROM magazine_ammo a
      JOIN mounts m ON m.kind='magazine' AND m.value=a.magazine COLLATE NOCASE;
    """)


def import_capture(root, rpt, destination, selected_run=None):
    manifest = json.loads((root / "validation/remaining/manifest.json").read_text())
    destination.mkdir(parents=True, exist_ok=False)
    report = {"status": "incomplete", "source": str(rpt), "suite_id": manifest["suite_id"]}
    inventories, observed, counts, probes = {}, {}, Counter(), set()
    begun, ended = False, False
    db = sqlite3.connect(destination / "snapshot.sqlite")
    try:
        schema(db)
        with gzip.open(destination / "records.jsonl.gz", "wt", encoding="utf-8", compresslevel=1) as archive:
            for run, sequence, record in iter_records(rpt, selected_run):
                if ended:
                    raise ValueError("Records found after END_SUITE")
                archive.write(encode(record) + "\n")
                kind = record[0]
                counts[kind] += 1
                if not begun and kind != "BEGIN_SUITE":
                    raise ValueError("Missing BEGIN_SUITE")
                if kind == "BEGIN_SUITE":
                    if begun or len(record) != 7 or record[1:3] != [1, manifest["suite_id"]] or record[3] not in {"full", "clean"}:
                        raise ValueError("Invalid/mismatched BEGIN_SUITE")
                    mode, mods = record[3], record[5]
                    if not mods or any(not isinstance(m, list) or len(m) < 4 or type(m[3]) is not bool for m in mods):
                        raise ValueError("Unverifiable loaded-mod metadata")
                    if mode == "clean" and any(not m[3] for m in mods):
                        raise ValueError("Clean batch contains non-official mods")
                    begun = True
                    report.update(run=run, mode=mode, product_version=record[4], loaded_mods=mods, world=record[6])
                elif kind == "INVENTORY":
                    _, section, names = record
                    if section not in SECTIONS or section in inventories or not all(isinstance(n, str) for n in names):
                        raise ValueError("Invalid section inventory")
                    names_set = {n.lower() for n in names}
                    if len(names_set) != len(names):
                        raise ValueError("Duplicate class in inventory")
                    inventories[section], observed[section] = names_set, set()
                elif kind == "CONFIG":
                    _, section, name, addons, ancestry, direct, fields = record
                    if section not in inventories or name.lower() not in inventories[section] or name.lower() in observed[section]:
                        raise ValueError("Unexpected/duplicate config class")
                    if not ancestry or ancestry[0].lower() != name.lower():
                        raise ValueError("Invalid class ancestry")
                    observed[section].add(name.lower())
                    db.execute("INSERT INTO configs VALUES(?,?,?,?,?)", (section, name, encode(addons), encode(ancestry), encode(direct)))
                    db.executemany("INSERT INTO fields VALUES(?,?,?,?,?)", ((section, name, encode(path), kind, encode(value)) for path, kind, value in flatten(fields)))
                elif kind == "MUZZLE":
                    _, weapon, muzzle, magazines, wells, compatible = record
                    for source, names in (("explicit", magazines), ("engine_muzzle", compatible)):
                        db.executemany("INSERT OR IGNORE INTO weapon_magazines VALUES(?,?,?,?)", ((weapon, muzzle, name, source) for name in names))
                    db.executemany("INSERT OR IGNORE INTO muzzle_wells VALUES(?,?,?)", ((weapon, muzzle, name) for name in wells))
                elif kind == "WEAPON_COMPAT":
                    _, weapon, magazines = record
                    db.executemany("INSERT OR IGNORE INTO weapon_magazines VALUES(?,?,?,?)", ((weapon, "*", name, "engine_all") for name in magazines))
                elif kind == "MOUNT":
                    _, vehicle, path, weapons, magazines = record
                    path = encode(path)
                    db.execute("INSERT INTO mount_nodes VALUES(?,?)", (vehicle, path))
                    for node_kind, names in (("weapon", weapons), ("magazine", magazines)):
                        db.executemany("INSERT OR IGNORE INTO mounts VALUES(?,?,?,?)", ((vehicle, path, node_kind, name) for name in names))
                elif kind == "PROBE":
                    _, section, name, path, node = record
                    key = (section, name, tuple(path))
                    if key in probes:
                        raise ValueError("Duplicate probe")
                    list(flatten([[path[-1], node]]))
                    probes.add(key)
                    db.execute("INSERT INTO probes VALUES(?,?,?,?)", (section, name, encode(path), encode(node)))
                elif kind == "END_SUITE":
                    if len(record) != 8 or record[1:4] != [1, manifest["suite_id"], report["mode"]] or record[4] != sequence or record[6] != 0:
                        raise ValueError("Incomplete batch, mismatched footer or recursion limit encountered")
                    expected_counts = [[s, len(inventories[s])] for s in inventories]
                    if set(inventories) != SECTIONS or record[5] != expected_counts or observed != inventories:
                        raise ValueError("Captured config inventory is incomplete")
                    if any(not inventories[s] for s in ("CfgWeapons", "CfgMagazines", "CfgAmmo", "CfgVehicles", "CfgPatches")):
                        raise ValueError("Critical config section is empty")
                    expected_probes = {(s, n, tuple(p)) for s, n, p in manifest["probes"]} if report["mode"] == "full" else set()
                    if probes != expected_probes:
                        raise ValueError("Targeted probes are incomplete")
                    pilot = record[7]
                    if report["mode"] == "full":
                        report["pilot_summary"] = pilot
                        if len(pilot) == 4 and type(pilot[0]) is int:
                            pilot_manifest = json.loads((root / "helmet-pilot/manifest.json").read_text())
                            _, pilot_records = read_records(rpt, pilot[3], b"A3BALPILOT")
                            result = validate_pilot(pilot_records, pilot_manifest)
                            if [result["checked_classes"], result["checked_fields"], result["failure_count"]] != pilot[:3]:
                                raise ValueError("Pilot summary disagrees with framed verification")
                            report["pilot_verification"] = result
                        elif pilot not in (["missing_or_aborted"], ["not_requested"]):
                            raise ValueError("Invalid pilot result")
                    elif pilot != ["not_requested"]:
                        raise ValueError("Unexpected pilot in clean capture")
                    ended = True
                    report["sections"] = dict(expected_counts)
                else:
                    raise ValueError(f"Unexpected record kind: {kind}")
                if sequence % 1000 == 0:
                    db.commit()
            if not ended:
                raise ValueError("Missing END_SUITE; batch did not finish")
        with rpt.open("rb") as stream:
            report["rpt_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        report.update(status="complete", record_counts=dict(counts),
                      limits="Config associations only. Dynamic script attachments and armor damage mechanics are not proven; held changes remain held.")
        for key, value in report.items():
            db.execute("INSERT INTO metadata VALUES(?,?)", (key, encode(value)))
        db.commit()
        return report
    except Exception as error:
        db.rollback()
        report.update(status="failed", error=str(error))
        raise
    finally:
        db.close()
        (destination / "import-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("rpt", type=Path)
    parser.add_argument("destination", type=Path, help="NEW directory for this snapshot")
    parser.add_argument("--run")
    args = parser.parse_args()
    result = import_capture(Path(__file__).resolve().parent, args.rpt, args.destination, args.run)
    print(json.dumps({k: result[k] for k in ("status", "run", "mode", "sections")}))
