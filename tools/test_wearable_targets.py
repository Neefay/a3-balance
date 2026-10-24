import copy
import unittest

from wearable_targets import build_wearable_targets, constant, preservation_guards, vest_tier
from wearable_assessment import name_role


def row(section, name, props, kind=None, parents=None, vanilla=False):
    result = {"section": section, "classname": name, "properties": props,
              "ancestry": [name] + (parents or []), "sourceAddons": ["A3_Characters_F"] if vanilla else ["custom"]}
    if kind:
        result["kind"] = kind
    return result


def vest(name, armor=20, through=.2, abdomen=None, vanilla=False):
    hp = {hit: {"hitpointName": "Hit" + hit, "armor": armor, "passThrough": through} for hit in ("Chest", "Diaphragm")}
    hp["Body"] = {"hitpointName": "HitBody", "passThrough": through}
    if abdomen is not None:
        hp["Abdomen"] = {"hitpointName": "HitAbdomen", "armor": abdomen, "passThrough": .6}
    return row("CfgWeapons", name, {"scope": 2, "ItemInfo": {"mass": 100, "HitpointsProtectionInfo": hp}}, "vest", vanilla=vanilla)


def uniform(name, unit, vanilla=False):
    return row("CfgWeapons", name, {"scope": 2, "ItemInfo": {"uniformClass": unit}}, "uniform", vanilla=vanilla)


def unit(name, structural=4, arm=3, vanilla=False):
    return row("CfgVehicles", name, {"armor": 2, "armorStructural": structural,
               "HitPoints": {"HitArms": {"armor": arm, "passThrough": 1, "radius": .1, "depends": "0"}}}, vanilla=vanilla)


def assessment(rows, roles=None):
    roles = roles or {}
    items, usage = [], {}
    for r in rows:
        name, kind = r["classname"], r["kind"]
        linked = r["properties"]["ItemInfo"].get("uniformClass")
        items.append({"classname": name, "kind": kind, "role": roles.get(name, "plate_carrier" if kind == "vest" else "ordinary_clothing"),
                      "status": "review", "reason": "fixture", "flags": [], "unit_class": linked})
        if linked:
            usage.setdefault(linked, []).append(name)
    return {"assessments": items, "unit_usage": [{"unit_class": name, "uniforms": names} for name, names in usage.items()]}


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.anchors = [vest("V_PlateCarrier2_rgr", vanilla=True), vest("V_PlateCarrierSpec_rgr", 24, .1, vanilla=True),
                        vest("V_PlateCarrier1_rgr", 16, .3, vanilla=True), vest("V_TacVest_blk_POLICE", 12, .4, vanilla=True),
                        vest("V_TacVest_khk", 8, .5, vanilla=True), vest("V_Chestrig_khk", 0, 1, vanilla=True),
                        uniform("U_B_CombatUniform_mcam", "B_Soldier_F", True), uniform("U_C_Poloshirt_blue", "C_man_F", True)]
        self.units = [unit("B_Soldier_F", vanilla=True), unit("C_man_F", vanilla=True)]

    def test_plate_changes_preserve_partial_coverage_geometry_and_source(self):
        custom = vest("rhsusf_mbav", 28, .1, abdomen=3)
        rows = self.anchors + [custom]
        before = copy.deepcopy(rows)
        result = build_wearable_targets(rows, self.units, assessment(rows))
        edits = result["changes"]
        self.assertTrue(edits)
        self.assertTrue(all(c["path"][2] != "Abdomen" for c in edits))
        self.assertTrue(all(c["path"][-1] in {"armor", "passThrough"} for c in edits))
        self.assertEqual(rows, before)
        self.assertEqual(result["targets"][-1]["status"], "proposed_partial_wearable_change")

    def test_mixed_extended_armor_keeps_weaker_abdomen(self):
        custom = vest("rhs_6b13", 28, .1, abdomen=22)
        rows = self.anchors + [custom]
        result = build_wearable_targets(rows, self.units, assessment(rows, {"rhs_6b13": "extended_armor"}))
        self.assertTrue(result["changes"])
        self.assertTrue(all(c["path"][2] != "Abdomen" for c in result["changes"]))
        self.assertEqual(result["targets"][-1]["reference_class"], "V_PlateCarrierSpec_rgr")

    def test_load_bearing_existing_regions_get_unarmored_state_without_new_regions(self):
        custom = vest("Belt_BLK", 1, .2)
        rows = self.anchors + [custom]
        result = build_wearable_targets(rows, self.units, assessment(rows, {"Belt_BLK": "load_bearing"}))
        self.assertEqual({c["proposed"] for c in result["changes"]}, {0, 1})
        self.assertTrue(all(c["anchors"] == ["V_Chestrig_khk"] for c in result["changes"]))

    def test_text_fields_are_held_while_numeric_fields_can_be_targeted(self):
        custom = vest("custom_carrier", "PLATE_ARMOR + 3", .1)
        rows = self.anchors + [custom]
        result = build_wearable_targets(rows, self.units, assessment(rows))
        self.assertEqual(len(result["targets"][-1]["held_fields"]), 2)
        self.assertTrue(all(isinstance(c["old"], (int, float)) for c in result["changes"]))
        self.assertEqual(result["targets"][-1]["status"], "proposed_partial_wearable_change")

    def test_uniform_targets_use_actual_unit_paths_and_preserve_geometry(self):
        custom = uniform("custom_uniform", "custom_unit")
        rows = self.anchors + [custom]
        units = self.units + [unit("custom_unit", .4, 5)]
        result = build_wearable_targets(rows, units, assessment(rows))
        self.assertEqual(len(result["changes"]), 2)
        self.assertTrue(all(c["section"] == "CfgVehicles" and c["classname"] == "custom_unit" for c in result["changes"]))
        self.assertEqual({tuple(c["path"]) for c in result["changes"]}, {("armorStructural",), ("HitPoints", "HitArms", "armor")})

    def test_boolean_text_pass_through_is_written_as_the_vanilla_number(self):
        custom = uniform("custom_uniform", "custom_unit")
        rows = self.anchors + [custom]
        mod_unit = unit("custom_unit", 4, 3)
        mod_unit["properties"]["HitPoints"]["HitArms"]["passThrough"] = "true"
        result = build_wearable_targets(rows, self.units + [mod_unit], assessment(rows))
        edit = next(c for c in result["changes"] if c["path"] == ["HitPoints", "HitArms", "passThrough"])
        self.assertEqual((edit["old"], edit["old_text"], edit["proposed"]), (1, "true", 1))
        self.assertFalse(result["targets"][-1]["held_fields"])

    def test_civilian_globals_are_held_without_affecting_limb_normalization(self):
        custom = uniform("civilian", "custom_unit")
        rows = self.anchors + [custom]
        result = build_wearable_targets(rows, self.units + [unit("custom_unit", .4, 5)], assessment(rows, {"civilian": "civilian_clothing"}))
        self.assertFalse(any(c["path"] == ["armorStructural"] for c in result["changes"]))
        self.assertTrue(any(c["path"] == ["HitPoints", "HitArms", "armor"] for c in result["changes"]))
        self.assertEqual(result["targets"][-1]["held_fields"][0]["reason"], "civilian_globals_need_in_game_test")

    def test_shared_unit_fields_emit_once_and_conflicting_selection_is_held(self):
        a, b = uniform("a", "custom_unit"), uniform("b", "custom_unit")
        rows = self.anchors + [a, b]
        units = self.units + [unit("custom_unit", .4)]
        result = build_wearable_targets(rows, units, assessment(rows))
        self.assertEqual(len(result["changes"]), 1)
        b["properties"]["scope"] = 0
        result = build_wearable_targets(rows, units, assessment(rows))
        self.assertFalse(result["changes"])
        self.assertEqual(result["targets"][-2]["status"], "review_shared_unit_target_conflict")

    def test_unknown_vest_is_only_capped_and_specialists_get_no_edits(self):
        custom = vest("unknown_vest", 999, .001)
        weak = vest("weak_unknown", 22, .3)
        eod = vest("custom_eod", 999, .001)
        rows = self.anchors + [custom, weak, eod]
        roles = {"unknown_vest": "unidentified", "weak_unknown": "unidentified", "custom_eod": "explosive_specialist"}
        result = build_wearable_targets(rows, self.units, assessment(rows, roles))
        self.assertEqual({c["classname"] for c in result["changes"]}, {"unknown_vest"})
        self.assertEqual({(c["path"][-1], c["proposed"]) for c in result["changes"]}, {("armor", 24), ("passThrough", .1)})
        self.assertTrue(all(c["rule"] == "vanilla_ceiling_cap" for c in result["changes"]))
        statuses = [t["status"] for t in result["targets"][-3:]]
        self.assertEqual(statuses, ["proposed_ceiling_cap", "review_no_selected_vest_tier", "review_no_selected_vest_tier"])
        self.assertIsNone(vest_tier(custom, "explosive_specialist"))

    def test_flak_and_light_carrier_use_their_own_vanilla_rungs(self):
        self.assertEqual(vest_tier(vest("V_Simc_vest_pasgt"), "soft_fragmentation"), "V_TacVest_blk_POLICE")
        self.assertEqual(vest_tier(vest("custom_tactical_vest"), "soft_fragmentation"), "V_TacVest_khk")
        self.assertEqual(vest_tier(vest("UK3CB_V_MBAV_RIFLEMAN"), "plate_carrier"), "V_PlateCarrier1_rgr")
        self.assertEqual(vest_tier(vest("rhsusf_spcs"), "plate_carrier"), "V_PlateCarrier2_rgr")
        self.assertEqual(vest_tier(vest("rhsusf_plateframe_rifleman"), "plate_carrier"), "V_PlateCarrier1_rgr")
        self.assertEqual(vest_tier(vest("rhsusf_mbss_coy"), "plate_carrier"), "V_PlateCarrier1_rgr")
        custom = vest("V_Simc_flak_55", 12, .5)
        rows = self.anchors + [custom]
        result = build_wearable_targets(rows, self.units, assessment(rows, {"V_Simc_flak_55": "soft_fragmentation"}))
        self.assertEqual({(c["path"][-1], c["proposed"]) for c in result["changes"]}, {("passThrough", .4)})

    def test_existing_vanilla_profile_match_keeps_its_distinct_tier(self):
        custom = vest("custom_light_carrier", 16, .3)
        rows = self.anchors + [custom]
        report = assessment(rows)
        report["assessments"][-1]["status"] = "matches_vanilla_profile"
        result = build_wearable_targets(rows, self.units, report)
        self.assertFalse(result["changes"])
        self.assertEqual(result["targets"][-1]["status"], "matches_vanilla_profile")

    def test_legacy_uniform_armor_is_not_silently_replaced_with_zero(self):
        custom = uniform("cbrn", "custom_unit")
        rows = self.anchors + [custom]
        report = assessment(rows)
        report["assessments"][-1]["flags"] = ["legacy_item_fields"]
        result = build_wearable_targets(rows, self.units + [unit("custom_unit")], report)
        self.assertFalse(result["changes"])
        self.assertEqual(result["targets"][-1]["status"], "review_uniform_item_fields")

    def test_rflak_is_not_flak_and_actual_flak_remains_soft(self):
        custom = vest("BRM_LBT_BROWN_RFLAK")
        self.assertEqual(name_role(custom), "plate_carrier")
        self.assertEqual(name_role(vest("V_Simc_flak_55")), "soft_fragmentation")

    def test_constant_text_values_are_evaluated_like_the_engine(self):
        self.assertEqual([constant(v) for v in ("22+ 3", "3*0.4", "28 + \t\t3", 7)], [25, 3 * .4, 31, 7])
        self.assertEqual([constant(v) for v in ("true", "ARMOR+3", "__import__('os')", "1/0", "")], [None] * 5)
        custom = vest("UK3CB_V_Eagle_Vest_RIF", "22+ 3", .2)
        self.assertEqual(name_role(custom), "plate_carrier")
        rows = self.anchors + [custom]
        result = build_wearable_targets(rows, self.units, assessment(rows))
        armor = [c for c in result["changes"] if c["path"][-1] == "armor"]
        self.assertEqual({(c["old"], c["old_text"], c["proposed"]) for c in armor}, {(25, "22+ 3", 20)})

    def test_v8_vest_family_identifications(self):
        self.assertEqual(name_role(vest("UK3CB_LDF_B_V_Vest_KKZ10_GEO")), "plate_carrier")
        self.assertEqual(name_role(vest("rhssaf_vest_md99_woodland")), "extended_armor")
        pilot = vest("UK3CB_V_Pilot_Vest")
        self.assertEqual(name_role(pilot), "soft_fragmentation")
        self.assertEqual(vest_tier(pilot, "soft_fragmentation"), "V_TacVest_blk_POLICE")
        osprey = vest("UK3CB_BAF_V_Pilot_A")
        osprey["ancestry"] += ["UK3CB_BAF_V_Osprey_Mk2_Base"]
        self.assertEqual(vest_tier(osprey, "soft_fragmentation"), "V_PlateCarrierSpec_rgr")

    def test_guards_use_actual_child_key_casing_and_skip_own_targeted_fields(self):
        parent = row("CfgVehicles", "parent", {"HitPoints": {"HitArms": {"armor": 5}}})
        child = row("CfgVehicles", "child", {"hitpoints": {"hitarms": {"Armor": 7}}}, parents=["parent"])
        edit = {"section": "CfgVehicles", "classname": "parent", "path": ["HitPoints", "HitArms", "armor"], "proposed": 3}
        result = preservation_guards([parent, child], [edit])
        self.assertEqual(result[0]["path"], ["hitpoints", "hitarms", "Armor"])
        self.assertEqual(result[0]["retain"], 7)
        child_edit = dict(edit, classname="child", path=["hitpoints", "hitarms", "Armor"])
        self.assertFalse(preservation_guards([parent, child], [edit, child_edit]))

    def test_missing_descendant_path_remains_unknown(self):
        child = row("CfgWeapons", "child", {}, parents=["parent"])
        result = preservation_guards([child], [{"section": "CfgWeapons", "classname": "parent", "path": ["armor"], "proposed": 0}])
        self.assertEqual(result[0]["status"], "review_missing_descendant_path")
        self.assertFalse(result[0]["present"])
        self.assertIsNone(result[0]["retain"])


if __name__ == "__main__":
    unittest.main()
