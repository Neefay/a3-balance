import copy
import unittest
from unittest.mock import patch

import draft_balance as draft
import ammunition_policy


def helmet(name, display, armor, through=.5, scope=2, addons=None):
    return {"section": "CfgWeapons", "classname": name, "kind": "headgear", "sourceAddons": addons or ["custom"],
            "properties": {"scope": scope, "displayName": display, "ItemInfo": {"mass": 30,
                "HitpointsProtectionInfo": {"Skull": {"HitpointName": "HitHead", "armor": armor, "PassThrough": through}}}}}


class DraftTests(unittest.TestCase):
    def test_inheritance_review_tracks_indirect_children_and_separates_sections(self):
        rows = [
            {"section": "CfgAmmo", "classname": "CHILD", "ancestry": ["CHILD", "middle", "root"]},
            {"section": "CfgWeapons", "classname": "helmet", "ancestry": ["helmet", "root"]}]
        changes = [{"section": "CfgAmmo", "classname": "Root"}]
        result = draft.inheritance_impacts(rows, changes, {"child": ["mag_child"], "root": ["mag_root"]})
        self.assertEqual(result[0]["potentialDescendants"], [{"classname": "CHILD", "alsoProposed": False}])
        self.assertEqual(result[0]["referencingMagazines"]["CHILD"], ["mag_child"])

    def test_names_do_not_match_substrings_and_special_equipment_is_excluded(self):
        self.assertIsNone(draft.helmet_rule(helmet("test", "Parachute beret", 6)))
        self.assertIsNone(draft.helmet_rule(helmet("test_FAST", "FAST bump helmet", 6)))
        self.assertIsNone(draft.helmet_rule(helmet("test_M1", "M1 liner", 2)))
        self.assertIsNone(draft.helmet_rule(helmet("test_ACH", "ACH", 0)))
        self.assertEqual(draft.helmet_rule(helmet("BRM_ACH_GREEN", "Combat helmet", 15))[:3],
                         ("ordinary_composite", 6, .5))
        self.assertEqual(draft.helmet_rule(helmet("BRM_M1H_GREEN", "M1", 8))[:3], ("derived_steel_light_vanilla", 4, .5))

    def test_v7_ladder_identifications(self):
        rule = lambda name, display="", armor=8: (draft.helmet_rule(helmet(name, display, armor)) or (None,))[0]
        self.assertEqual(rule("BRM_LWH_UN", "(UN)LWH", 10), "ordinary_composite")
        self.assertEqual(rule("BRM_6B7_COMS_UN", "6B7 COMS", 10), "ordinary_composite")
        self.assertEqual(rule("UK3CB_AAF_H_MK6_DIGI", "MK6 Helmet Digital Black"), "ordinary_composite")
        for name, display in [("H_Simc_SVN_M1C_op", "M1C Helmet"), ("SNS_M51_Camo", "Casque M51"),
                              ("sns_m53_scrim_2", "[NL] M53 Helm"), ("BRM_VZ53", "VZ 53 helmet"),
                              ("UK3CB_H_M1_Helmet_Covered_TAN", "M1 Helmet Covered (Tan)"), ("UK3CB_H_HSAT_PTYPE", "HSAT P-TYPE"),
                              ("UK3CB_H_MKIV_Helmet", "MK IV Helmet")]:
            self.assertEqual(rule(name, display), "derived_steel_light_vanilla", name)
        self.assertEqual(rule("BRM_CVC_GUNFIGHTER", "CVC Gunfighter Mod.", 12), "vanilla_crew_helmet")
        self.assertEqual(rule("rhsusf_cvc_helmet", "ACVC-H, MK-1697", 6), "vanilla_crew_helmet")
        self.assertEqual(rule("UK3CB_H_Heli_Crew", "Helicopter Crew Helmet"), "vanilla_heli_aircrew")
        self.assertEqual(rule("rhs_altyn_visordown", "Altyn (visor down)", 6), "vanilla_heavy_visored")
        self.assertIsNone(rule("custom_cover", "Helmet cover (Woodland)"))

    def test_v8_family_identifications(self):
        rule = lambda name, display="", armor=6: (draft.helmet_rule(helmet(name, display, armor)) or (None,))[0]
        for name, display, expected in [
                ("rhsusf_hgu56p_visor", "HGU-56/P (Visor)", "vanilla_heli_aircrew"), ("BRM_SPH4_GREEN", "SPH-4 Visor helmet", "vanilla_heli_aircrew"),
                ("rhsusf_ihadss", "IHADSS", "vanilla_heli_aircrew"), ("rhs_zsh7a_mike", "ZSh-7A", "vanilla_jet_pilot"),
                ("RHS_jetpilot_usaf", "Jet Pilot Helmet", "vanilla_jet_pilot"), ("rhs_6b48", "6B48", "vanilla_crew_helmet"),
                ("rhssaf_helmet_m97_olive_nocamo", "M97 (Olive)", "ordinary_composite"), ("UK3CB_LDF_B_H_UHB13_GEO", "UHB13 (Geometric)", "ordinary_composite"),
                ("rhs_6b28_ess", "6B28 (ESS)", "ordinary_composite"), ("rhs_stsh81", "STSh-81", "ordinary_composite"),
                ("UK3CB_H_Ballistic_Mask_BLK", "Ballistic Mask (Black)", "ordinary_composite"),
                ("UK3CB_APD_B_H_Motorbike_Helmet", "Motorbike Helmet", "vanilla_racing_helmet"),
                ("H_Simc_protec_full", "[US-SF] Pro-Tec Helmet", "vanilla_hard_hat")]:
            self.assertEqual(rule(name, display), expected, name)
        self.assertIsNone(rule("custom_protector", "Protector Helmet (Hex)", 8))

    def test_text_constants_and_vanilla_model_twins(self):
        self.assertEqual(draft.helmet_rule(helmet("text_ACH", "ACH", "12+ 3"))[:3], ("ordinary_composite", 6, .5))
        self.assertIsNone(draft.helmet_rule(helmet("macro_ACH", "ACH", "HELMET_ARMOR")))
        vanilla = helmet("H_HelmetHBK_ear_F", "Modular Helmet", 7, addons=["A3_Characters_F"])
        twin = helmet("custom_mhb15", "MHB15 Ear", 12)
        for row in (vanilla, twin):
            row["properties"]["ItemInfo"]["uniformModel"] = "\\A3\\Characters_F_Enoch\\Headgear\\H_HelmetHBK_01_ear_F.p3d"
        twins = draft.model_twins([vanilla, twin])
        self.assertEqual(draft.helmet_rule(twin, twins), ("vanilla_model_twin", 7, .5, ["H_HelmetHBK_ear_F"]))

    def test_unidentified_helmet_is_capped_at_the_vanilla_ceiling(self):
        gear = [helmet("H_HelmetB", "Combat helmet", 6, addons=["A3_Characters_F"]),
                helmet("H_HelmetLeaderO_ocamo", "Defender", 12, addons=["A3_Characters_F"]),
                helmet("custom_mystery", "Mystery lid", 20, .2), helmet("custom_ok", "Other lid", 11)]
        with patch.multiple(draft, ARMOR_ANCHORS=[("headgear", "ordinary_composite", "H_HelmetB")],
                            AMMO_ANCHORS=[], MODERN_ANCHORS=["H_HelmetB"]), patch.object(draft, "build_ammunition_policy",
                            return_value={"changes": [], "mapping": []}):
            _, coverage, changes = draft.make_proposal(gear, [])
        self.assertEqual({(c["classname"], c["path"][-1], c["proposed"]) for c in changes},
                         {("custom_mystery", "armor", 12), ("custom_mystery", "PassThrough", .5)})
        self.assertEqual({r["classname"]: r["status"] for r in coverage}["custom_ok"], "review_identity")

    def test_vanilla_paths_hidden_classes_and_held_named_ammunition(self):
        anchors = [("headgear", "ordinary_composite", "H_HelmetB")]
        steel = ["rhsgref_helmet_M1_bare", "rhs_ssh60", "rhs_ssh68_2"]
        gear = [helmet("H_HelmetB", "Combat helmet", 6, addons=["A3_Characters_F"])]
        gear += [helmet("H_HelmetB_light", "Light", 4, addons=["A3_Characters_F"])]
        gear += [helmet(name, "Steel", 2, addons=["rhs_c_troops"]) for name in steel]
        gear += [helmet("custom_ACH", "ACH", 15, .8), helmet("base_ACH", "ACH", 15, scope=0)]
        gear += [helmet("text_ACH", "ACH", 15, "HELMET_PASSTHROUGH")]
        ammo = []
        for name, hit, caliber, speed in [("B_556x45_Ball", 9, .44, 900),
                ("rhs_ammo_556x45_M855_Ball", 9, .44, 900),
                ("rhs_ammo_556x45_Mk262_Ball", 10, .6, 830),
                ("ACE_556x45_Ball_Mk262", 9, 1.6, 920)]:
            ammo.append({"section": "CfgAmmo", "classname": name, "ancestry": [name],
                         "sourceAddons": ["rhs_ammo"] if name.startswith("rhs") else ["other"],
                         "properties": {"hit": hit, "caliber": caliber, "typicalSpeed": speed,
                                        "simulation": "shotBullet", "explosive": 0, "indirectHit": 0}})
        before = copy.deepcopy((gear, ammo))
        with patch.multiple(draft, ARMOR_ANCHORS=anchors,
                            AMMO_ANCHORS=[("5.56x45", "generic_ball", "B_556x45_Ball")],
                            MODERN_ANCHORS=["H_HelmetB"]), patch.multiple(ammunition_policy,
                            FAMILIES=[("556x45", "5.56x45", "B_556x45_Ball", "rhs_ammo_556x45_M855_Ball")],
                            SHORT_GENERIC={}):
            _, coverage, changes = draft.make_proposal(gear, ammo)
            statuses = {row["classname"]: row["status"] for row in coverage}
            self.assertEqual(statuses["H_HelmetB"], "reference_preserved")
            self.assertEqual(statuses["base_ACH"], "review_nonpublic_class")
            self.assertEqual(statuses["text_ACH"], "review_text_or_missing")
            self.assertEqual({row["classname"] for row in changes}, {"custom_ACH", *steel})
            first = next(c for c in changes if c["classname"] == "custom_ACH")
            self.assertEqual(first["path"], ["ItemInfo", "HitpointsProtectionInfo", "Skull", "armor"])
            self.assertEqual((first["old"], first["proposed"]), (15, 6))
            self.assertEqual(statuses["ACE_556x45_Ball_Mk262"], "deferred_handheld_usage_proof")
            self.assertFalse(any(c["kind"] == "projectile" for c in changes))
            self.assertEqual(statuses[steel[0]], "proposed_change")
            derived = next(c for c in changes if c["classname"] == steel[0])
            self.assertEqual(derived["confidence"], "derived_vanilla_gameplay_rule")
            self.assertEqual(derived["anchors"], ["H_HelmetB_light"])
            gear[0]["properties"]["ItemInfo"]["HitpointsProtectionInfo"]["Skull"]["armor"] = 7
            with self.assertRaisesRegex(ValueError, "Vanilla reference changed"):
                draft.make_proposal(gear, ammo)
        gear[0] = before[0][0]
        self.assertEqual((gear, ammo), before)


if __name__ == "__main__":
    unittest.main()
