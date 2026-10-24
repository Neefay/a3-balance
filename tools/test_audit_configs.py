import unittest

from audit_configs import build_report, protection, semantic


def vest(name, armor, mass=40):
    return {"classname": name, "kind": "vest", "sourceAddons": ["addon"], "properties": {
        "scope": 2, "ItemInfo": {"uniformModel": "\\test\\vest.p3d", "mass": mass,
            "HitpointsProtectionInfo": {"Chest": {"armor": armor, "passThrough": .3}}}}}


class AuditTests(unittest.TestCase):
    def test_profiles_ignore_mass_and_parent_labels_but_keep_missing_values(self):
        first, second = vest("a", 16, 40), vest("b", 16, 90)
        second["properties"]["ItemInfo"]["HitpointsProtectionInfo"]["Chest"]["$parent"] = "Base"
        report = build_report([first, second, vest("c", 28)], {}, [])
        self.assertEqual(report["summary"]["protection_profiles"], {"vest": 2})
        self.assertEqual(len(report["shared_models"]), 1)
        self.assertEqual(report["shared_models"][0]["profileCount"], 2)
        self.assertEqual(report["shared_models"][0]["publicProfileCount"], 2)
        self.assertNotEqual(semantic({"armor": 0}), semantic({}))

    def test_text_expressions_are_preserved_and_flagged_for_review(self):
        report = build_report([vest("a", "28 + 3")], {}, [])
        self.assertEqual(report["findings"][0]["reason"], "numeric_field_stored_as_text")
        chest = report["profiles"][0]["protection"]["item"]["hitpointsprotectioninfo"]["chest"]
        self.assertEqual(chest["armor"], "28 + 3")

    def test_uniform_profiles_follow_unit_protection_and_keep_unknown_links(self):
        first = {"classname": "u", "kind": "uniform", "properties": {
            "ItemInfo": {"uniformClass": "UNIT"}}}
        self.assertEqual(protection(first, {"unit": {"Armor": 2}})["unit"], {"armor": 2})
        self.assertEqual(protection(first, {})["unit"], {"unresolved": "UNIT"})


if __name__ == "__main__":
    unittest.main()
