import copy
from contextlib import closing
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from extract_rpt import parse_sqf
from import_remaining_capture import flatten, import_capture, iter_records
from prepare_remaining_captures import prepare, sqf


def literal(value):
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, list):
        return "[" + ",".join(literal(v) for v in value) + "]"
    return sqf(value)


def frames(records, run="fixture", marker="A3BALBATCH"):
    result = []
    for index, record in enumerate(records, 1):
        codes = list(map(ord, literal(record)))
        pieces = [codes[n:n + 96] for n in range(0, len(codes), 96)]
        for part, piece in enumerate(pieces, 1):
            result.append(f'12:34:56 "{marker}|{run}|{index}|{part}|{len(pieces)}|{json.dumps(piece)}|END"\n')
    return "".join(result)


def fixture(root, mode="clean"):
    dest = root / "validation/remaining"
    dest.mkdir(parents=True)
    probes = [["CfgWeapons", "Missing", ["ItemInfo", "armor"]]]
    (dest / "manifest.json").write_text(json.dumps({"suite_id": "fixture", "probes": probes}))
    mods = [["Arma 3", "A3", True, True]]
    if mode == "full":
        mods.append(["Pilot", "pilot", False, False])
    records = [["BEGIN_SUITE", 1, "fixture", mode, ["Arma 3", 222], mods, "VR"]]
    inventories = [("CfgWeapons", ["Rifle"]), ("CfgMagazines", ["Mag"]),
                   ("CfgMagazineWells", []), ("CfgAmmo", ["Ball"]),
                   ("CfgVehicles", ["Car"]), ("CfgGlasses", []), ("CfgPatches", ["A3"])]
    for section, names in inventories:
        records.append(["INVENTORY", section, names])
        for name in names:
            fields = [["ammo", ["text", "Ball"]]] if section == "CfgMagazines" else [["scope", ["number", 2]]]
            if section == "CfgWeapons":
                fields.append(["ItemInfo", ["class", "Base", ["armor"], [["armor", ["number", 20]], ["passThrough", ["missing", []]]]]])
            records.append(["CONFIG", section, name, ["A3"], [name], ["scope"], fields])
            if section == "CfgWeapons":
                records.extend([["MUZZLE", name, "this", ["Mag"], ["STANAG"], ["Mag"]], ["WEAPON_COMPAT", name, ["Mag"]]])
            if section == "CfgVehicles":
                records.extend([["MOUNT", name, [], ["Rifle"], []], ["MOUNT", name, ["Turrets", "MainTurret"], ["Rifle"], ["Mag"]]])
    if mode == "full":
        records.append(["PROBE", *probes[0], ["missing", []]])
    records.append(["END_SUITE", 1, "fixture", mode, len(records) + 1,
                    [[s, len(n)] for s, n in inventories], 0,
                    ["not_requested"] if mode == "clean" else ["missing_or_aborted"]])
    return records


class RemainingCaptureTests(unittest.TestCase):
    def test_streamed_snapshot_preserves_missing_values_and_vehicle_edges(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = fixture(root, "full")
            rpt = root / "capture.rpt"
            rpt.write_text(frames(records), encoding="utf-8")
            output = root / "snapshot"
            report = import_capture(root, rpt, output)
            self.assertEqual(report["status"], "complete")
            self.assertEqual(report["pilot_summary"], ["missing_or_aborted"])
            with closing(sqlite3.connect(output / "snapshot.sqlite")) as db:
                self.assertEqual(db.execute("SELECT kind,value FROM fields WHERE path=?", ('["ItemInfo","passThrough"]',)).fetchone(), ("missing", "[]"))
                self.assertEqual(db.execute("SELECT ammo,magazine,vehicle FROM projectile_vehicle_magazines").fetchall(), [("Ball", "Mag", "Car")])
                self.assertEqual(db.execute("SELECT well FROM muzzle_wells").fetchone(), ("STANAG",))
                self.assertEqual(db.execute("SELECT data FROM probes").fetchone(), ('["missing",[]]',))
            with gzip.open(output / "records.jsonl.gz", "rt", encoding="utf-8") as stream:
                self.assertEqual([json.loads(line) for line in stream], records)
            with self.assertRaises(FileExistsError):
                import_capture(root, rpt, output)

    def test_complete_pilot_is_tied_to_its_own_run_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = fixture(root, "full")
            (root / "helmet-pilot").mkdir()
            manifest = {"build_id": "pilot", "materialized_iteminfo_classes": 1, "verified_fields_expected": 1}
            (root / "helmet-pilot/manifest.json").write_text(json.dumps(manifest))
            pilot = [["BEGIN_PILOT", 1, "pilot", 1, ["Arma 3"], records[0][5]], ["END_PILOT", 1, "pilot", 2, 1, 1, 0, 0]]
            records[-1][-1] = [1, 1, 0, "pilot_run"]
            rpt = root / "capture.rpt"
            rpt.write_text(frames(records) + frames(pilot, "pilot_run", "A3BALPILOT"))
            report = import_capture(root, rpt, root / "snapshot")
            self.assertTrue(report["pilot_verification"]["passed"])
            records[-1][-1][2] = 1
            rpt.write_text(frames(records) + frames(pilot, "pilot_run", "A3BALPILOT"))
            with self.assertRaisesRegex(ValueError, "disagrees"):
                import_capture(root, rpt, root / "bad")

    def test_truncation_missing_duplicate_and_inconsistent_frames_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = [["TEST", "☃" * 150]]
            valid = frames(record).splitlines(keepends=True)
            self.assertEqual(len(valid), 2)
            cases = [valid[:-1], [valid[0], *valid], [valid[0][:-25] + "\n", valid[1]],
                     [valid[0], valid[1].replace("|2|2|", "|2|3|")]]
            rpt = root / "capture.rpt"
            for case in cases:
                rpt.write_text("".join(case), encoding="utf-8")
                with self.assertRaises(ValueError):
                    list(iter_records(rpt))
            rpt.write_text("".join(valid), encoding="utf-8")
            self.assertEqual(list(iter_records(rpt))[0][2], record[0])

    def test_multiple_runs_require_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            rpt = Path(temp) / "capture.rpt"
            rpt.write_text(frames([["TEST", 1]], "old") + frames([["TEST", 2]], "new"))
            with self.assertRaisesRegex(ValueError, "Multiple"):
                list(iter_records(rpt))
            self.assertEqual(list(iter_records(rpt, "new"))[0][2], ["TEST", 2])

    def test_invalid_provenance_inventory_footer_and_probe_never_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            records = fixture(root)
            cases = []
            bad = copy.deepcopy(records)
            bad[0][5][0][3] = False
            cases.append(bad)
            bad = copy.deepcopy(records)
            bad[2][2] = "Unexpected"
            cases.append(bad)
            cases.append(records[:-1])
            bad = copy.deepcopy(records)
            bad[-1][6] = 1
            cases.append(bad)
            bad = copy.deepcopy(records)
            bad[-1][4] -= 1
            cases.append(bad)
            rpt = root / "capture.rpt"
            for index, case in enumerate(cases):
                rpt.write_text(frames(case))
                output = root / str(index)
                with self.assertRaises(ValueError):
                    import_capture(root, rpt, output)
                self.assertEqual(json.loads((output / "import-report.json").read_text())["status"], "failed")

    def test_config_tree_types_are_not_coerced_and_depth_limit_fails(self):
        tree = [["HP", ["class", "Base", ["armor"], [["armor", ["text", "28 + 3"]]]]]]
        self.assertEqual(list(flatten(tree))[-1], (("HP", "armor"), "text", "28 + 3"))
        for invalid in ([["x", ["limit", []]]], [["x", ["number", "20"]]], [["x", ["number", True]]], [["x", ["missing", 0]]]):
            with self.assertRaises(ValueError):
                list(flatten(invalid))

    def test_generated_scripts_include_pilot_and_probes_only_in_full_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "proposal").mkdir()
            (root / "helmet-pilot").mkdir()
            (root / "capture_remaining.template.sqf").write_bytes((Path(__file__).parent / "capture_remaining.template.sqf").read_bytes())
            for name, rows in (("wearable_targets", [{"held_fields": [{"section": "CfgVehicles", "classname": "Unit", "path": ["armor"]}]}]),
                               ("wearable_assessments", [{"classname": "Uniform", "unit_class": "Unit", "status": "review_uniform_item_fields"}]),
                               ("wearable_preservation_guards", [{"section": "CfgWeapons", "classname": "Rig", "path": ["ItemInfo", "armor"], "present": False}])):
                (root / f"proposal/{name}.json").write_text(json.dumps(rows))
            pilot = '[] spawn {\nprivate _checks = [];\n};\n'
            (root / "helmet-pilot/verify_helmet_pilot.sqf").write_text(pilot, newline="")
            (root / "helmet-pilot/manifest.json").write_text(json.dumps({"build_id": "pilot", "verification_script_sha256": hashlib.sha256(pilot.encode()).hexdigest()}))
            result = prepare(root)
            full = (root / "validation/remaining/capture_full.sqf").read_text()
            clean = (root / "validation/remaining/capture_clean.sqf").read_text()
            self.assertIn("scriptDone _pilotHandle", full)
            self.assertNotIn("scriptDone _pilotHandle", clean)
            self.assertIn('"Uniform"', full)
            self.assertNotIn('"Uniform"', clean)
            self.assertIn('compatibleMagazines [_name, _muzzle]', full)
            self.assertIn('"Turrets"', full)
            self.assertIn('"TransportPylonsComponent"', full)
            self.assertNotIn("__PILOT_BLOCK__", full)
            self.assertEqual(parse_sqf(sqf(["a\\b", 'a"b', [1]])), ["a\\b", 'a"b', [1]])
            for mode in ("full", "clean"):
                path = root / "validation/remaining" / result["scripts"][mode]["file"]
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), result["scripts"][mode]["sha256"])
            # Without a helmet pilot the full capture carries no pilot block and records none.
            for name in ("verify_helmet_pilot.sqf", "manifest.json"):
                (root / "helmet-pilot" / name).unlink()
            prepare(root)
            full = (root / "validation/remaining/capture_full.sqf").read_text()
            self.assertNotIn("_pilotHandle", full)
            self.assertNotIn("__PILOT_BLOCK__", full)
            self.assertIsNone(json.loads((root / "validation/remaining/manifest.json").read_text())["pilot_build_id"])


if __name__ == "__main__":
    unittest.main()
