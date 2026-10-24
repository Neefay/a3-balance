import copy
import unittest
from unittest.mock import patch

import ammunition_policy as policy


def ammo(name, hit=9, caliber=.5, speed=900, parents=None, rhs=False, **extra):
    return {"section": "CfgAmmo", "classname": name, "ancestry": [name] + (parents or []),
            "sourceAddons": ["rhs_c_ammo"] if rhs else ["test"],
            "properties": {"simulation": "shotBullet", "hit": hit, "caliber": caliber,
                           "typicalSpeed": speed, "explosive": 0, "indirectHit": 0,
                           "submunitionAmmo": "", **extra}}


class AmmunitionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.family = [("556x45", "5.56x45", "B_556x45_Ball", "rhs_ammo_556x45_M855_Ball")]
        self.base = [ammo("B_556x45_Ball", 9, .9, 900),
                     ammo("rhs_ammo_556x45_M855_Ball", 8, .4, 800, rhs=True)]

    def run_policy(self, rows, usage=None):
        with patch.multiple(policy, FAMILIES=self.family, SHORT_GENERIC={}):
            if usage is not None:
                return policy.build_ammunition_policy(rows, usage=usage)
            return policy.build_ammunition_policy(rows, verified_handheld_projectiles=[r["classname"] for r in rows])

    def test_ball_uses_vanilla_triplet_and_ap_uses_derived_ladder(self):
        rows = self.base + [ammo("rhs_ammo_556x45_M995_AP", 6, .9, 1000, rhs=True)]
        before = copy.deepcopy(rows)
        result = self.run_policy(rows)
        mapped = {row["classname"]: row for row in result["mapping"]}
        self.assertEqual(mapped["B_556x45_Ball"]["proposed"], policy.triplet(self.base[0]))
        self.assertEqual(mapped[self.base[1]["classname"]]["proposed"], policy.triplet(self.base[0]))
        # Author's damage coefficient ratio 0.6 is clamped to 0.75; caliber is ball x1.5.
        self.assertEqual(mapped[rows[-1]["classname"]]["proposed"], {"hit": 6.75, "caliber": 1.35, "typicalSpeed": 900})
        self.assertEqual(mapped[rows[-1]["classname"]]["basis"], "derived_specialized_ladder")
        self.assertEqual(mapped[rows[-1]["classname"]]["reference_ball"], "rhs_ammo_556x45_M855_Ball")
        self.assertTrue(all(c["anchors"] == ["B_556x45_Ball"] for c in result["changes"]))
        self.assertEqual({c["rule"] for c in result["changes"] if c["classname"].endswith("_AP")}, {"derived_specialized_ladder"})
        self.assertEqual(rows, before)

    def test_missing_handheld_usage_proof_prevents_edits(self):
        with patch.multiple(policy, FAMILIES=self.family, SHORT_GENERIC={}):
            result = policy.build_ammunition_policy(self.base)
        self.assertFalse(result["changes"])
        self.assertEqual(result["mapping"][1]["status"], "deferred_handheld_usage_proof")
        self.assertIsNone(result["mapping"][1]["proposed"])
        self.assertEqual(result["mapping"][1]["candidate"], policy.triplet(self.base[0]))

    def test_unproven_member_blocks_the_whole_cartridge(self):
        rows = self.base + [ammo("rhs_ammo_556x45_M995_AP", 6, .9, 1000, rhs=True)]
        usage = {"rhs_ammo_556x45_M855_Ball": {"verdict": "handheld_only"},
                 "rhs_ammo_556x45_M995_AP": {"verdict": "unproven"}}
        result = self.run_policy(rows, usage)
        self.assertFalse(result["changes"])
        statuses = {row["classname"]: row["status"] for row in result["mapping"]}
        self.assertEqual(statuses["rhs_ammo_556x45_M855_Ball"], "deferred_cartridge_incomplete")
        self.assertEqual(statuses["rhs_ammo_556x45_M995_AP"], "deferred_handheld_usage_proof")
        self.assertFalse(result["cartridges"][0]["ready"])

    def test_vehicle_shared_rounds_change_with_their_cartridge(self):
        rows = self.base + [ammo("rhs_ammo_556x45_M995_AP", 6, .9, 1000, rhs=True)]
        usage = {"rhs_ammo_556x45_M855_Ball": {"verdict": "vehicle_shared"},
                 "rhs_ammo_556x45_M995_AP": {"verdict": "handheld_only"}}
        result = self.run_policy(rows, usage)
        self.assertTrue(result["cartridges"][0]["ready"])
        self.assertEqual({c["classname"] for c in result["changes"]}, {"rhs_ammo_556x45_M855_Ball", "rhs_ammo_556x45_M995_AP"})

    def test_unidentified_designator_blocks_its_cartridge_unless_unused(self):
        rows = self.base + [ammo("custom_556x45_SPR", 10, .6, 870)]
        result = self.run_policy(rows)
        self.assertFalse(result["changes"])
        self.assertEqual(result["mapping"][-1]["status"], "review_variant_identity")
        usage = {"rhs_ammo_556x45_M855_Ball": {"verdict": "handheld_only"}, "custom_556x45_SPR": {"verdict": "no_magazines"}}
        self.assertTrue(self.run_policy(rows, usage)["changes"])

    def test_observed_order_checks_still_report_while_ladder_passes(self):
        rows = self.base + [ammo("custom_556x45_AP", caliber=.2), ammo("custom_556x45_Subsonic", caliber=1.2, speed=320)]
        result = self.run_policy(rows)
        checks = {r["classname"]: r for r in result["penetration_checks"]}
        self.assertEqual([r["status"] for r in checks.values()], ["review_penetration_order"] * 2)
        self.assertEqual(checks["custom_556x45_AP"]["ladder_status"], "ladder_passes")
        self.assertEqual(checks["custom_556x45_Subsonic"]["ladder_status"], "ladder_violation")
        self.assertEqual(result["mapping"][-1]["status"], "preserved_subsonic_observed")
        self.assertIsNone(result["mapping"][-1]["proposed"])

    def test_grau_designators_are_recognized(self):
        roles = {name: policy.role({"classname": name}) for name in
                 ("rhs_B_762x54_7BZ3_Ball", "rhs_B_545x39_7N22_Ball", "rhs_B_762x54_7N13_Ball",
                  "rhs_B_762x54_7N1_Ball", "rhs_B_545x39_7N6_Ball", "rhs_B_545x39_7U1_Ball")}
        self.assertEqual(list(roles.values()), ["armor_piercing_named", "armor_piercing_named", "enhanced_ball_named",
                                                "match_named", "ball_named", "subsonic_named"])

    def test_v8_identified_rounds_join_the_ladder(self):
        rows = self.base + [ammo("rhssaf_ammo_556x45_SPR", 10, .6, 870, rhs=True)]
        result = self.run_policy(rows)
        entry = result["mapping"][-1]
        self.assertEqual((entry["ladder_role"], entry["status"]), ("match_named", "proposed_change"))
        self.assertEqual(entry["proposed"]["caliber"], .9)
        self.assertEqual(policy.role({"classname": "rhs_B_762x39_Ball_89"}), "ball_named")

    def test_wrong_cartridge_ancestor_never_establishes_identity(self):
        row = ammo("custom_762x67_Ball", parents=["rhs_ammo_556x45_M855_Ball", "B_556x45_Ball"])
        result = self.run_policy(self.base + [row])
        entry = result["mapping"][-1]
        self.assertEqual(entry["status"], "preserved_outside_scale")
        self.assertIsNone(entry["proposed"])
        self.assertEqual(result["preservation_guards"][0]["classname"], row["classname"])

    def test_inherited_ap_subsonic_and_blank_are_not_flattened_to_ball(self):
        rows = [ammo("custom_556x45_Ball_AP", hit=8, caliber=.4, speed=800,
                     parents=["rhs_ammo_556x45_M855_Ball", "B_556x45_Ball"]),
                ammo("custom_556x45_Ball_SD", speed=300, parents=["B_556x45_Ball"]),
                ammo("custom_556x45_blank", submunitionAmmo="blank_helper")]
        result = self.run_policy(self.base + rows)
        ap, subsonic, blank = result["mapping"][-3:]
        self.assertAlmostEqual(ap["proposed"]["caliber"], .9 * 1.5)
        self.assertEqual(ap["ladder_role"], "armor_piercing_named")
        self.assertIsNone(subsonic["proposed"])
        self.assertEqual(blank["status"], "preserved_special_function")

    def test_rhs_subsonic_has_no_automatic_vanilla_equivalent(self):
        row = ammo("rhs_ammo_556x45_Subsonic", hit=3, caliber=.2, speed=300, rhs=True)
        result = self.run_policy(self.base + [row])
        self.assertIsNone(result["mapping"][-1]["proposed"])

    def test_tracer_inheriting_specialized_construction_follows_its_construction(self):
        anchor = ammo("rhs_ammo_556x45_M855A1_Ball", caliber=.7, rhs=True)
        child = ammo("custom_556x45_Ball_Tracer_Red", caliber=.7, parents=[anchor["classname"], "B_556x45_Ball"], tracerScale=2)
        result = self.run_policy(self.base + [anchor, child])
        entry = result["mapping"][-1]
        self.assertEqual(entry["ladder_role"], "enhanced_ball_named")
        self.assertAlmostEqual(entry["proposed"]["caliber"], .9 * 1.2)
        self.assertTrue(entry["tracer_name_flag"])
        self.assertNotIn("tracerScale", {row["path"][0] for row in result["changes"]})

    def test_nonbullet_children_get_preservation_guards(self):
        special = ammo("custom_556x45_Ball_AP", parents=["rhs_ammo_556x45_M855_Ball"])
        nonbullet = ammo("child_shell", parents=["rhs_ammo_556x45_M855_Ball"], simulation="shotShell")
        result = self.run_policy(self.base + [special, nonbullet])
        self.assertEqual({r["classname"] for r in result["preservation_guards"]}, {nonbullet["classname"]})
        self.assertEqual(len(result["mapping"]), 3)

    def test_vanilla_classes_remain_unchanged_even_when_generic(self):
        row = ammo("B_556x45_Ball_Tracer_Red", hit=7)
        row["sourceAddons"] = ["A3_Weapons_F"]
        result = self.run_policy(self.base + [row])
        self.assertEqual(result["mapping"][-1]["status"], "reference_preserved")
        self.assertIsNone(result["mapping"][-1]["proposed"])

    def test_nonkinetic_and_text_values_are_held_for_review(self):
        rows = [ammo("custom_556x45_Ball", explosive=.2), ammo("text_556x45_Ball", hit="9 + 1")]
        result = self.run_policy(self.base + rows)
        self.assertEqual([row["status"] for row in result["mapping"][-2:]], ["review_terminal_model"] * 2)


if __name__ == "__main__":
    unittest.main()
