import copy
import unittest
from unittest.mock import patch

import wearable_assessment as assessment


def gear(name, kind, display="", info=None, vanilla=False):
    return {"section": "CfgWeapons", "classname": name, "kind": kind, "ancestry": [name],
            "sourceAddons": ["A3_Characters_F"] if vanilla else ["custom"],
            "properties": {"scope": 2, "displayName": display, "ItemInfo": info or {}}}


def hp(armor=8, through=.5, region="Chest"):
    return {"HitpointsProtectionInfo": {region: {"hitpointName": "HitChest", "armor": armor, "passThrough": through}}}


def unit(name="unit", parents=None, **props):
    return {"section": "CfgVehicles", "classname": name, "ancestry": [name] + (parents or []),
            "sourceAddons": ["custom"], "properties": {"armor": 2, "armorStructural": 4,
                "HitPoints": {"HitChest": {"armor": 1, "passThrough": .8}}, **props}}


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        self.base = [gear("V_Base", "vest", info=hp(), vanilla=True),
                     gear("U_Base", "uniform", info={"uniformClass": "unit"}, vanilla=True)]

    def run_assessment(self, rows, units=None):
        with patch.multiple(assessment, VEST_REFERENCES={"soft_fragmentation": ["V_Base"]},
                            UNIFORM_REFERENCES={"ordinary_clothing": ["U_Base"]}):
            return assessment.build_assessments(rows, units or [unit()])

    def test_names_classify_construction_without_using_armor_strength(self):
        for name, display, expected in [
            ("rhsusf_iotv", "IOTV", "extended_armor"),
            ("BRM_MBSS_v1", "MBSS Rifleman", "plate_carrier"),
            ("UK3CB_PASGT", "PASGT Vest", "soft_fragmentation"),
            ("Belt_BLK", "Belt", "load_bearing"),
            ("V_M69", "M69 Vest/40mm Ammo vest", "soft_fragmentation"),
            ("V_GL", "Carrier GL Rig", "explosive_specialist")]:
            self.assertEqual(assessment.name_role(gear(name, "vest", display)), expected)
        self.assertEqual(assessment.name_role(gear("KZS", "uniform", "KZS Suit")), "ordinary_clothing")

    def test_null_and_missing_and_text_and_number_are_distinct(self):
        diffs = assessment.differences({"x": None, "armor": "8", "p": 0}, {"armor": 8, "p": 0})
        self.assertEqual(len(diffs), 2)
        missing = next(d for d in diffs if d["path"] == ["x"])
        self.assertTrue(missing["current_present"])
        self.assertFalse(missing["reference_present"])

    def test_region_labels_align_by_hitpoint_and_inputs_are_unchanged(self):
        rows = self.base + [gear("Custom", "vest", "Tactical vest", hp(region="Torso"))]
        before = copy.deepcopy(rows)
        result = self.run_assessment(rows)
        self.assertEqual(result["assessments"][-1]["status"], "matches_vanilla_profile")
        self.assertFalse(result["comparisons"])
        self.assertEqual(rows, before)

    def test_load_bearing_conflict_is_flagged_even_if_numeric_profile_matches(self):
        result = self.run_assessment(self.base + [gear("Belt_BLK", "vest", "Belt", hp())])
        row = result["assessments"][-1]
        self.assertEqual(row["status"], "review_role_protection_conflict")
        self.assertIn("load_bearing_has_protection", row["flags"])

    def test_missing_unit_is_unknown_and_shared_units_have_descendants(self):
        rows = self.base + [gear("Custom", "uniform", info={"uniformClass": "UNIT"}),
                            gear("Missing", "uniform", info={"uniformClass": "absent"})]
        result = self.run_assessment(rows, [unit(), unit("child", ["UNIT"], uniformClass="Custom")])
        resolved, missing = result["assessments"][-2:]
        self.assertEqual(resolved["shared_uniform_count"], 2)
        self.assertEqual(resolved["unit_descendant_count"], 1)
        self.assertEqual(resolved["declared_wearer_count"], 1)
        self.assertEqual(missing["status"], "unresolved_uniform_unit")
        self.assertFalse(any(c["classname"] == "Missing" for c in result["comparisons"]))

    def test_text_values_and_legacy_uniform_armor_are_reviewed_separately(self):
        rows = self.base + [gear("Vest", "vest", "Tactical vest", hp(armor="4 + 3")),
                            gear("Suit", "uniform", info={"uniformClass": "unit", "armor": 20})]
        result = self.run_assessment(rows)
        self.assertEqual(result["assessments"][-2]["status"], "review_text_protection")
        self.assertEqual(result["assessments"][-1]["status"], "review_uniform_item_fields")
        self.assertEqual(result["summary"]["automatic_field_changes"], 0)

    def test_vanilla_is_preserved_and_nonvanilla_anchor_is_rejected(self):
        result = self.run_assessment(self.base)
        self.assertTrue(all(r["status"] == "vanilla_reference_preserved" for r in result["assessments"]))
        self.base[0]["sourceAddons"] = ["rhs"]
        with self.assertRaisesRegex(ValueError, "Not a loaded vanilla"):
            self.run_assessment(self.base)

    def test_missing_region_is_not_assigned_zero(self):
        result = self.run_assessment(self.base + [gear("Vest", "vest", "Tactical vest", {"mass": 40})])
        diff = next(c for c in result["comparisons"] if c["path"] == ["regions", "hitchest", "armor"])
        self.assertFalse(diff["current_present"])
        self.assertIsNone(diff["current"])
        self.assertEqual(diff["reference"], 8)


if __name__ == "__main__":
    unittest.main()
