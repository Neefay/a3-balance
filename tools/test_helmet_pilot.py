import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

from build_helmet_pilot import literal, make_plan, pack_pbo
from import_helmet_verification import validate_pilot
from compare_clean_baseline import compare
from test_build_query_db import fixture


def data():
    def weapon(name, parents, armor, mass):
        return {"section": "CfgWeapons", "classname": name, "ancestry": [name] + parents,
                "sourceAddons": ["A3_Characters_F"], "properties": {"scope": 2, "displayName": name,
                    "ItemInfo": {"$parent": "HeadgearItem", "mass": mass, "uniformModel": "\\model\\helmet.p3d",
                        "allowedSlots": [901, 605], "HitpointsProtectionInfo": {
                            "Head": {"hitpointName": "HitHead", "armor": armor, "passThrough": .5},
                            "Neck": {"hitpointName": "HitNeck", "armor": 3, "passThrough": .8}}}}}
    rows = [{"section": "CfgPatches", "classname": "A3_Characters_F", "sourceAddons": [], "properties": {}, "ancestry": ["A3_Characters_F"]},
            weapon("Base", [], 6, 30), weapon("Target", ["Base"], 15, 40), weapon("Child", ["Target", "Base"], 12, 50)]
    edit = {"section": "CfgWeapons", "classname": "Target", "kind": "headgear",
            "path": ["ItemInfo", "HitpointsProtectionInfo", "Head", "armor"], "old": 15, "proposed": 6}
    baseline = {"helmet_baseline_ready": True, "capture_sha256": "capture"}
    return rows, [edit], baseline


class PilotTests(unittest.TestCase):
    def test_helmet_only_config_keeps_descendant_mass_model_neck_and_ancestry(self):
        rows, changes, baseline = data()
        before = copy.deepcopy(rows)
        source, checks, manifest = make_plan(rows, changes, baseline)
        self.assertNotIn("CfgVehicles", source)
        self.assertNotIn("CfgAmmo", source)
        self.assertIn("class Target: Base", source)
        self.assertIn("class Child: Target", source)
        self.assertEqual((manifest["target_classes"], manifest["preserved_descendant_classes"]), (1, 1))
        observed = {name: {tuple(path): value for path, kind, value in fields if kind != "class"} for name, ancestry, fields in checks}
        self.assertEqual(observed["Target"][("ItemInfo", "HitpointsProtectionInfo", "Head", "armor")], 6)
        self.assertEqual(observed["Child"][("ItemInfo", "HitpointsProtectionInfo", "Head", "armor")], 12)
        self.assertEqual(observed["Target"][("ItemInfo", "mass")], 40)
        self.assertEqual(observed["Child"][("ItemInfo", "mass")], 50)
        self.assertEqual(observed["Target"][("ItemInfo", "HitpointsProtectionInfo", "Neck", "armor")], 3)
        self.assertEqual(rows, before)
        self.assertEqual(make_plan(rows, changes, baseline), (source, checks, manifest))

    def test_bad_baseline_missing_dependency_and_out_of_scope_edits_are_rejected(self):
        rows, edits, baseline = data()
        with self.assertRaises(ValueError):
            make_plan(rows, edits, dict(baseline, helmet_baseline_ready=False))
        with self.assertRaises(ValueError):
            make_plan(rows[1:], edits, baseline)
        edits[0]["path"] = ["ItemInfo", "mass"]
        with self.assertRaises(ValueError):
            make_plan(rows, edits, baseline)

    def test_config_literal_quotes_backslashes_arrays_and_nonfinite_values(self):
        self.assertEqual(literal('a "quote" \\path'), '"a ""quote"" \\path"')
        self.assertEqual(literal([1, "text"]), '{1,"text"}')
        for value in (float("nan"), True, "bad\nline"):
            with self.assertRaises(ValueError):
                literal(value)

    def test_pbo_independent_header_payload_and_checksum_readback(self):
        config = b"class CfgPatches {};\n"
        archive = pack_pbo(config)
        stream = io.BytesIO(archive)
        def cstring():
            result = bytearray()
            while True:
                byte = stream.read(1)
                self.assertTrue(byte, "Truncated PBO header")
                if byte == b"\0":
                    return bytes(result)
                result.extend(byte)
        self.assertEqual(cstring(), b"")
        self.assertEqual(struct.unpack("<5I", stream.read(20)), (0x56657273, 0, 0, 0, 0))
        self.assertEqual((cstring(), cstring(), cstring()), (b"prefix", b"a3bal_helmets_pilot", b""))
        self.assertEqual(cstring(), b"config.cpp")
        method, original, offset, stamp, length = struct.unpack("<5I", stream.read(20))
        self.assertEqual((method, original, offset, stamp, length), (0, len(config), 0, 0, len(config)))
        self.assertEqual(stream.read(21), b"\0" * 21)
        self.assertEqual(stream.read(length), config)
        self.assertEqual(stream.read(1), b"\0")
        self.assertEqual(stream.read(20), hashlib.sha1(archive[:-21]).digest())
        self.assertEqual(stream.read(), b"")

    def test_runtime_summary_must_cover_all_fields_and_report_failure(self):
        manifest = {"build_id": "build", "materialized_iteminfo_classes": 2, "verified_fields_expected": 100}
        begin = ["BEGIN_PILOT", 1, "build", 2, ["Arma 3"], []]
        end = ["END_PILOT", 1, "build", 2, 2, 100, 0, 0]
        self.assertTrue(validate_pilot([begin, end], manifest)["passed"])
        end[5] = 99
        with self.assertRaises(ValueError):
            validate_pilot([begin, end], manifest)
        failure = ["FAILURE", "Target", ["armor"], 6, 15]
        self.assertFalse(validate_pilot([begin, failure, ["END_PILOT", 1, "build", 3, 2, 100, 1, 1]], manifest)["passed"])

    def test_baseline_comparison_records_drift_without_touching_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            (root / "validation").mkdir()
            manifest = {"requests_sha256": "fixture", "requests": [["CfgAmmo", "rhs_ammo_test", ["hit"]]]}
            capture = {"manifest_sha256": "fixture", "classes": [["CLASS", "CfgAmmo", "rhs_ammo_test"]],
                       "fields": [["FIELD", "CfgAmmo", "rhs_ammo_test", ["hit"], "number", 10]],
                       "loaded_mods": [["Arma 3", "A3", True, True]], "run": "fixture", "product_version": []}
            (root / "validation/clean_capture_manifest.json").write_text(json.dumps(manifest))
            path = root / "validation/clean-vanilla-capture.json"
            path.write_text(json.dumps(capture))
            # The fixture database is built by the existing validated query builder.
            from build_query_db import build
            build(root)
            before = path.read_bytes()
            report = compare(root)
            self.assertEqual(report["differences"][0]["observed"], 9)
            self.assertEqual(report["differences"][0]["clean"], 10)
            self.assertFalse(report["helmet_baseline_ready"])
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
