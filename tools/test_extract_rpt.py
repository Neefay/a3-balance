import json
from pathlib import Path
import tempfile
import unittest
import csv

from extract_rpt import extract, parse_sqf, compact
from inventory import inventory


def frame(record, number):
    # The test strings below use SQF syntax, not Python/JSON string escaping.
    codes = list(map(ord, record))
    parts = [codes[i:i+80] for i in range(0, len(codes), 80)]
    return "".join(f"17:00:00 A3EQ|1.05789e+06_125856|{number}|{i}|{len(parts)}|"
                   f"{json.dumps(part)}|END\n" for i, part in enumerate(parts))


HEADER = '["BEGIN","ARMA_EQUIPMENT_DUMP",2,[],[]]'
AMMO = '["CfgAmmo","test",["test"],["addon"],[["hit","number",12],["label","text","a""b\\c"]]]'
FOOTER = '["END",[["CfgAmmo",1]],2]'


class ExtractTests(unittest.TestCase):
    def test_sqf_strings_numbers_and_unicode(self):
        self.assertEqual(parse_sqf('["a""b","C:\\mods\\new",-1.2e-3,true,["é中\n"]]'),
                         ['a"b', 'C:\\mods\\new', -.0012, True, ['é中\n']])

    def test_projection_retains_muzzle_modes_and_protection(self):
        source = {"muzzles": ["this", "GL"], "GL": {"modes": ["Single"],
                  "Single": {"dispersion": .1, "sound": [1, 2]}},
                  "ItemInfo": {"HitpointsProtectionInfo": {"Chest": {"armor": 16}}}}
        result = compact("CfgWeapons", source)
        self.assertEqual(result["GL"]["Single"], {"dispersion": .1})
        self.assertEqual(result["ItemInfo"], source["ItemInfo"])

    def test_complete_stream_and_corruption(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rpt = root / "test.rpt"
            text = "unrelated log\n" + frame(HEADER, 0) + frame(AMMO, 1) + frame(FOOTER, 2)
            rpt.write_text(text, encoding="utf-8")
            summary = extract(rpt, root / "ok")
            self.assertEqual(summary["status"], "complete")
            self.assertEqual(summary["sections"], {"CfgAmmo": 1})
            row = json.loads((root / "ok" / "configs.relevant.jsonl").read_text())
            self.assertEqual(row["properties"]["label"], 'a"b\\c')
            # Drop a chunk; a partially decoded dataset must never be labelled complete.
            lines = text.splitlines(keepends=True)
            rpt.write_text("".join(lines[:2] + lines[3:]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "chunk"):
                extract(rpt, root / "bad")
            self.assertEqual(json.loads((root / "bad" / "summary.json").read_text())["status"], "incomplete")

    def test_missing_footer_and_wrong_counts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rpt = root / "test.rpt"
            for i, footer in enumerate(("", frame('["END",[["CfgAmmo",2]],2]', 2))):
                rpt.write_text(frame(HEADER, 0) + frame(AMMO, 1) + footer, encoding="utf-8")
                with self.assertRaises(ValueError):
                    extract(rpt, root / str(i))

    def test_salvage_reports_lost_records_without_fabricating_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rpt = root / "test.rpt"
            # Record 1 loses its final chunk; record 2 loses its first chunk;
            # record 3 is wholly absent. Record 4 remains intact.
            first = frame(AMMO, 1).splitlines(keepends=True)[:-1]
            second = frame(AMMO, 2).splitlines(keepends=True)[1:]
            rpt.write_text(frame(HEADER, 0) + "".join(first + second) + frame(AMMO, 4)
                           + frame('["END",[["CfgAmmo",4]],5]', 5), encoding="utf-8")
            result = extract(rpt, root / "recovered", salvage=True)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["missing_record_ranges"], [[1, 3]])
            self.assertEqual(result["missing_by_section"], {"CfgAmmo": 3})
            self.assertEqual(result["sections"], {"CfgAmmo": 1})

    def test_inventory_links_uniforms_and_preserves_unknown_values(self):
        uniform = ["CfgWeapons", "uniform", ["Uniform_Base"], ["addon"],
                   [["scope", "number", 2], ["ItemInfo", "class", ["UniformItem", [
                       ["type", "number", 801], ["uniformClass", "text", "UNIT"],
                       ["mass", "number", 40]]]]]]
        unit = ["CfgVehicles", "unit", ["Man"], ["addon"], [["armor", "number", 2]]]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rpt = root / "test.rpt"
            rpt.write_text(frame(HEADER, 0) + frame(json.dumps(uniform), 1) + frame(json.dumps(unit), 2)
                           + frame('["END",[["CfgWeapons",1],["CfgVehicles",1]],3]', 3), encoding="utf-8")
            extract(rpt, root / "data")
            report = inventory(root / "data")
            self.assertEqual(report["unresolved_uniform_references"], {})
            with (root / "data" / "wearables.csv").open(encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row["linkedUnitArmor"], "2")
            self.assertEqual(row["itemArmor"], "")
            self.assertEqual(row["linkedUnitRecovered"], "True")


if __name__ == "__main__":
    unittest.main()
