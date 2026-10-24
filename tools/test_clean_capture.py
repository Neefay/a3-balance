import copy
import json
from pathlib import Path
import tempfile
import unittest

from import_clean_capture import read_capture, validate
from prepare_clean_capture import prepare
from build_review_queue import family


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"requests_sha256": "fixture", "requests": [["CfgWeapons", "H_ref", ["ItemInfo"]]]}
        self.records = [["BEGIN", 1, "fixture", ["Arma 3"], [["Arma 3", "A3", True, True]]],
                        ["CLASS", "CfgWeapons", "H_ref", ["A3_Characters_F"], ["H_ref"]],
                        ["FIELD", "CfgWeapons", "H_ref", ["ItemInfo", "armor"], "number", 4],
                        ["END", 1, "fixture", 4, []]]

    def test_chunked_rpt_roundtrip_and_preserved_missing_field(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.rpt"
            lines = []
            for index, record in enumerate(self.records, 1):
                codes = list(map(ord, json.dumps(record)))
                pieces = [codes[n:n+25] for n in range(0, len(codes), 25)]
                lines.extend(f'12:34:56 A3BALREF|run|{index}|{part}|{len(pieces)}|{json.dumps(piece)}|END\n'
                             for part, piece in enumerate(pieces, 1))
            path.write_text("".join(lines))
            result = read_capture(path, self.manifest)
            self.assertEqual(result["fields"][0][-1], 4)
            self.assertEqual(result["run"], "run")
            missing = copy.deepcopy(self.records)
            missing[2] = ["FIELD", "CfgWeapons", "H_ref", ["ItemInfo"], "missing", []]
            self.assertEqual(validate(missing, self.manifest)["fields"][0][-2], "missing")
            path.write_text("".join(lines[:-1]))
            with self.assertRaises(ValueError):
                read_capture(path, self.manifest)

    def test_truncated_header_is_diagnosed_and_a_new_run_can_be_selected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "capture.rpt"
            damaged = '12:34:56 "A3BALREF|old|1|1|2|[91,34,66,69\n'
            frames = []
            for index, record in enumerate(self.records, 1):
                codes = json.dumps(list(map(ord, json.dumps(record))))
                frames.append(f'12:34:56 A3BALREF|new|{index}|1|1|{codes}|END\n')
            path.write_text(damaged + "".join(frames))
            with self.assertRaisesRegex(ValueError, "Truncated/malformed.*records \\[1\\]"):
                read_capture(path, self.manifest, "old")
            with self.assertRaisesRegex(ValueError, "multiple captures"):
                read_capture(path, self.manifest)
            self.assertEqual(read_capture(path, self.manifest, "new")["run"], "new")

    def test_modded_incomplete_and_duplicate_captures_are_rejected(self):
        bad = copy.deepcopy(self.records)
        bad[0][4][0][3] = False
        with self.assertRaisesRegex(ValueError, "non-official"):
            validate(bad, self.manifest)
        with self.assertRaises(ValueError):
            validate(self.records[:-1], self.manifest)
        bad = self.records[:3] + [self.records[2]] + [["END", 1, "fixture", 5, []]]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate(bad, self.manifest)

    def test_capture_requests_include_linked_uniform_unit_and_bounded_frames(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "proposal").mkdir()
            (root / "proposal/anchors.json").write_text(json.dumps([
                {"section": "CfgWeapons", "classname": "H_ref"},
                {"section": "CfgWeapons", "classname": "U_ref", "unitClass": "B_ref"}]))
            (root / "capture_clean_vanilla.template.sqf").write_text(Path(__file__).with_name("capture_clean_vanilla.template.sqf").read_text())
            result = prepare(root)
            self.assertEqual(result["classes"], 3)
            script = (root / "validation/capture_clean_vanilla.sqf").read_text()
            self.assertNotIn("__REQUESTS__", script)
            self.assertIn('"CfgVehicles","B_ref"', script)
            self.assertIn("private _chunkSize = 96", script)
            # Include wide Unicode code points, separators, timestamp and quoted log wrapper.
            frame = '12:34:56 "A3BALREF|' + 'r' * 64 + '|100000|10000|10000|' + json.dumps([0x10ffff] * 96) + '|END"'
            self.assertLess(len(frame), 1000)
            self.assertIn("getLoadedModsInfo", script)

    def test_family_grouping_does_not_assign_a_balance_tier(self):
        self.assertEqual(family({"classname": "UK3CB_V_KKZ10_A", "properties": {}}), "KKZ10")
        self.assertEqual(family({"classname": "x", "properties": {"ItemInfo": {"uniformModel": "A/B/C.p3d"}}}), "Model family: a\\b\\c")


if __name__ == "__main__":
    unittest.main()
