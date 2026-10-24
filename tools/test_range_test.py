import json
from pathlib import Path
import tempfile
import unittest

from import_clean_capture import read_records
import import_range_test as importer

ROOT = Path(__file__).resolve().parent


def sqf_value(value):
    if isinstance(value, str):
        return '"' + value.replace('"', '""') + '"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ",".join(sqf_value(v) for v in value) + "]"
    return repr(value)


def frames(run, records):
    lines = []
    for number, record in enumerate(records, 1):
        chars = [ord(c) for c in sqf_value(record)]
        parts = [chars[i:i + 96] for i in range(0, len(chars), 96)]
        for index, part in enumerate(parts, 1):
            lines.append(f'"A3BALRANGE|{run}|{number}|{index}|{len(parts)}|{json.dumps(part).replace(" ", "")}|END"')
    return "\n".join(lines) + "\n"


class RangeTestTests(unittest.TestCase):
    manifest = {"suite_id": "suite", "trials": 2, "max_shots": 12, "expected_results": 4,
                "rounds": [{"cartridge": "5.56x45", "classname": "B_556x45_Ball", "role": "after"}],
                "vests": [{"classname": "", "role": "baseline", "tier": "no vest", "armor": 0, "passThrough": None},
                          {"classname": "V_PlateCarrier2_rgr", "role": "after", "tier": "plate", "armor": 20, "passThrough": .2}],
                "helmets": []}

    def records(self, results):
        begin = ["BEGIN_RANGE", 1, "suite", 1, 2, 2, 12, .35, ["Arma 3"], [], [["ace_medical_AIDamageThreshold", "1"]], [], True]
        return [begin] + results + [["END_RANGE", 1, "suite", len(results) + 2, len(results)]]

    def test_frames_round_trip_and_survivors_never_lower_the_median(self):
        values = [9, .87, 920]
        results = [["RESULT", "B_556x45_Ball", "chest", "", 1, 2, "unconscious", .4, values, ""],
                   ["RESULT", "B_556x45_Ball", "chest", "", 2, 4, "dead", .4, values, ""],
                   ["RESULT", "B_556x45_Ball", "chest", "V_PlateCarrier2_rgr", 1, 6, "unconscious", .1, values, "V_PlateCarrier2_rgr"],
                   ["RESULT", "B_556x45_Ball", "chest", "V_PlateCarrier2_rgr", 2, -1, "standing", .1, values, "V_PlateCarrier2_rgr"]]
        with tempfile.TemporaryDirectory() as folder:
            rpt = Path(folder) / "range.rpt"
            rpt.write_text("noise\n" + frames("run1", self.records(results)), encoding="utf-8")
            run, records = read_records(rpt, None, b"A3BALRANGE")
        self.assertEqual(run, "run1")
        begin, parsed = importer.validate(records, self.manifest)
        rows = {row["wearable"]: row for row in importer.summarize(parsed, self.manifest)}
        self.assertEqual(rows["(none)"]["median_shots"], 3)
        self.assertEqual(rows["V_PlateCarrier2_rgr"]["median_shots"], (6 + 13) / 2)
        self.assertEqual(rows["V_PlateCarrier2_rgr"]["incapacitated"], 1)
        rows["V_PlateCarrier2_rgr"]["median_shots"] = 13
        text = importer.markdown(list(rows.values()), begin, self.manifest)
        self.assertIn("| >12 |", text)
        self.assertIn("| 3 |", text)

    def test_incomplete_runs_are_refused(self):
        values = [9, .87, 920]
        results = [["RESULT", "B_556x45_Ball", "chest", "", 1, 2, "unconscious", .4, values, ""]]
        with self.assertRaisesRegex(ValueError, "Expected 4 trials"):
            importer.validate(self.records(results), self.manifest)
        broken = self.records(results)
        broken[-1][4] = 3
        with self.assertRaisesRegex(ValueError, "disagree"):
            importer.validate(broken, self.manifest)

    def test_vehicle_records_are_counted_and_summarized(self):
        manifest = dict(self.manifest, version=2, expected_results=0, expected_vehicle_results=2, vehicle_trials=2, vehicle_shots=8)
        values = [11.6, 1.8, 835]
        results = [["VEHICLE_RESULT", "B_556x45_Ball", "rhs_btr80_msv", 1, -1, "unhurt", .02, True, values],
                   ["VEHICLE_RESULT", "B_556x45_Ball", "rhs_btr80_msv", 2, 3, "hurt", .04, True, values]]
        begin = ["BEGIN_RANGE", 2, "suite", 1, 2, 2, 12, .35, ["Arma 3"], [], [], [], True, 1, 2, 8]
        records = [begin] + results + [["END_RANGE", 2, "suite", 4, 2]]
        begin, parsed = importer.validate(records, manifest)
        rows = importer.summarize_vehicles(parsed, manifest)
        self.assertEqual((rows[0]["crew_hurt"], rows[0]["first_hurt_shot"], rows[0]["vehicle_damage_mean"]), (1, 3, .03))
        self.assertIn("| `rhs_btr80_msv` | 1/2 (3) |", importer.markdown([], begin, manifest, rows))
        with self.assertRaisesRegex(ValueError, "vehicle trials"):
            importer.validate(records[:1] + results[:1] + [["END_RANGE", 2, "suite", 3, 1]], manifest)

    def test_prepared_script_is_complete_and_matches_its_manifest(self):
        folder = ROOT / "validation" / "range-test"
        if not (folder / "manifest.json").exists():
            self.skipTest("range test not prepared")
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        script = (folder / "range_test.sqf").read_text(encoding="utf-8")
        self.assertNotIn("__", script.replace("A3BAL_range_running", ""))
        self.assertIn(manifest["suite_id"], script)
        self.assertEqual(manifest["expected_results"],
                         len(manifest["rounds"]) * (len(manifest["vests"]) + len(manifest["helmets"])) * manifest["trials"])
        self.assertEqual(manifest["expected_vehicle_results"], len(manifest["rounds"]) * len(manifest["vehicles"]) * manifest["vehicle_trials"])
        after = {row["classname"] for row in manifest["vests"] + manifest["helmets"] if row["role"] == "after"}
        self.assertTrue({"V_PlateCarrier2_rgr", "V_PlateCarrierSpec_rgr", "H_HelmetB", "H_HelmetB_light"} <= after)


if __name__ == "__main__":
    unittest.main()
