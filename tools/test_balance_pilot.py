import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from build_balance_pilot import make_plan, split, untraced
from build_release import release_config, write_hemtt
from import_balance_verification import validate_part


def data():
    def helmet(name, parents, armor):
        return {"section": "CfgWeapons", "classname": name, "ancestry": [name] + parents, "sourceAddons": ["A3_Characters_F"],
                "properties": {"scope": 2, "ItemInfo": {"$parent": "HeadgearItem", "mass": 40, "HitpointsProtectionInfo": {
                    "Head": {"hitpointName": "HitHead", "armor": armor, "passThrough": .5}}}}}
    def unit(name, parents, chest):
        return {"section": "CfgVehicles", "classname": name, "ancestry": [name] + parents, "sourceAddons": ["A3_Characters_F"],
                "properties": {"scope": 1, "HitPoints": {"$parent": "HitPoints", "HitChest": {"$parent": "", "armor": chest, "name": "spine3"}}}}
    def ammo(name, parents, hit, caliber):
        return {"section": "CfgAmmo", "classname": name, "ancestry": [name] + parents, "sourceAddons": ["A3_Weapons_F"],
                "properties": {"hit": hit, "caliber": caliber, "typicalSpeed": 900, "airFriction": -0.001}}
    rows = [{"section": "CfgPatches", "classname": name, "sourceAddons": [], "properties": {}, "ancestry": [name]} for name in ("A3_Characters_F", "A3_Weapons_F")]
    rows += [helmet("HBase", [], 6), helmet("HTarget", ["HBase"], 15),
             unit("UBase", ["Land"], 2), unit("UTarget", ["UBase", "Land"], 2), unit("UChild", ["UTarget", "UBase", "Land"], 3),
             ammo("BulletBase", [], 8, 1), ammo("B_Anchor", ["BulletBase"], 9, 0.9), ammo("R_Target", ["BulletBase"], 9, 0.4),
             ammo("R_Child", ["R_Target", "BulletBase"], 9, 0.4)]
    edits = [{"section": "CfgWeapons", "classname": "HTarget", "kind": "headgear", "anchors": ["H_A"],
              "path": ["ItemInfo", "HitpointsProtectionInfo", "Head", "armor"], "old": 15, "proposed": 6},
             {"section": "CfgVehicles", "classname": "UTarget", "kind": "uniform_unit", "anchors": ["U_B_CombatUniform_mcam"],
              "path": ["HitPoints", "HitChest", "armor"], "old": 2, "proposed": 1},
             {"section": "CfgAmmo", "classname": "R_Target", "kind": "projectile", "anchors": ["B_Anchor"],
              "path": ["caliber"], "old": 0.4, "proposed": 0.9}]
    clean = {("CfgWeapons", "h_a", ("iteminfo", "hitpointsprotectioninfo", "head", "armor")): 6,
             ("CfgVehicles", "b_soldier_f", ("hitpoints", "hitchest", "armor")): 1,
             ("CfgAmmo", "b_anchor", ("hit",)): 9, ("CfgAmmo", "b_anchor", ("caliber",)): 0.9, ("CfgAmmo", "b_anchor", ("typicalspeed",)): 900}
    return rows, edits, {"helmet_baseline_ready": True, "capture_sha256": "capture"}, clean


def leaves(nodes, path=()):
    for key, kind, value in nodes:
        if kind == "class":
            yield from leaves(value, path + (key,))
        else:
            yield path + (key,), value


class BalancePilotTests(unittest.TestCase):
    def test_plan_materializes_targets_preserves_descendants_and_declares_roots(self):
        rows, edits, baseline, clean = data()
        before = copy.deepcopy(rows)
        source, checks, manifest = make_plan(rows, edits, baseline, clean)
        found = {(section, name): dict(leaves(nodes)) for section, name, ancestry, nodes in checks}
        self.assertEqual(found[("CfgWeapons", "HTarget")][("ItemInfo", "HitpointsProtectionInfo", "Head", "armor")], 6)
        self.assertEqual(found[("CfgWeapons", "HTarget")][("ItemInfo", "mass")], 40)
        self.assertEqual(found[("CfgVehicles", "UTarget")][("HitPoints", "HitChest", "armor")], 1)
        self.assertEqual(found[("CfgVehicles", "UChild")][("HitPoints", "HitChest", "armor")], 3)
        self.assertEqual(found[("CfgVehicles", "UBase")][("HitPoints", "HitChest", "armor")], 2)
        self.assertEqual(found[("CfgAmmo", "R_Target")], {("caliber",): 0.9})
        self.assertEqual(found[("CfgAmmo", "R_Child")], {("caliber",): 0.4})
        self.assertIn("    class Land;", source)
        self.assertIn("    class UBase: Land { class HitPoints; };", source)
        self.assertIn("        class HitPoints: HitPoints", source)
        self.assertNotIn("airFriction", source)
        self.assertEqual(manifest["by_kind"]["CfgVehicles"]["preserved_descendant_classes"], 1)
        self.assertEqual(rows, before)
        self.assertEqual(make_plan(rows, edits, baseline, clean), (source, checks, manifest))

    def test_values_must_trace_to_clean_vanilla(self):
        rows, edits, baseline, clean = data()
        edits[0]["proposed"] = 7
        with self.assertRaises(ValueError):
            make_plan(rows, edits, baseline, clean)
        rows, edits, baseline, clean = data()
        rig = {"section": "CfgWeapons", "classname": "HTarget", "kind": "vest", "anchors": ["H_A"],
               "path": ["ItemInfo", "HitpointsProtectionInfo", "Chest", "armor"], "old": 15, "proposed": 0}
        self.assertEqual(untraced(rows, [rig], clean), [])
        self.assertEqual(len(untraced(rows, [dict(rig, proposed=4)], clean)), 1)
        clean[("CfgAmmo", "b_anchor", ("typicalspeed",))] = 800
        self.assertEqual(len(untraced(rows, edits, clean)), 1)

    def test_out_of_scope_paths_and_bad_baseline_are_rejected(self):
        rows, edits, baseline, clean = data()
        with self.assertRaises(ValueError):
            make_plan(rows, edits, dict(baseline, helmet_baseline_ready=False), clean)
        edits[2]["path"] = ["airFriction"]
        with self.assertRaises(ValueError):
            make_plan(rows, edits, baseline, clean)

    def test_release_config_renames_only_the_patch_header(self):
        rows, edits, baseline, clean = data()
        source, _, _ = make_plan(rows, edits, baseline, clean)
        text = release_config(source)
        self.assertIn("    class a3bal_main", text)
        self.assertNotIn("a3bal_pilot", text)
        self.assertEqual(text.split("\nclass CfgWeapons", 1)[1], source.split("\nclass CfgWeapons", 1)[1])
        with self.assertRaises(ValueError):
            release_config(text)

    def test_hemtt_export_needs_a_passed_session_and_writes_the_addon(self):
        rows, edits, baseline, clean = data()
        source, _, _ = make_plan(rows, edits, baseline, clean)
        source = source.replace("class HTarget", "// Armor Level III\nclass HTarget", 1)
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            tools, pilot, session = project / "tools", project / "tools/balance-pilot", project / "tools/session"
            for folder in (project / ".hemtt", project / "addons/main", pilot / "source/a3bal_pilot", session):
                folder.mkdir(parents=True)
            (project / ".hemtt/project.toml").write_text('prefix = "a3bal"\n')
            (pilot / "source/a3bal_pilot/config.cpp").write_bytes(source.encode())
            (pilot / "manifest.json").write_text(json.dumps({"build_id": "build", "config_sha256": hashlib.sha256(source.encode()).hexdigest(),
                                                             "required_addons": ["A3_Characters_F"], "changed_fields": 3, "by_kind": {}}))
            (session / "session-report.json").write_text(json.dumps({"passed": False, "pilot_build_id": "build"}))
            with self.assertRaises(ValueError):
                write_hemtt(tools, pilot, session)
            (session / "session-report.json").write_text(json.dumps({"passed": True, "pilot_build_id": "build"}))
            info = write_hemtt(tools, pilot, session)
            config = (project / "addons/main/config.cpp").read_text(encoding="utf-8")
            self.assertIn("    class a3bal_main", config)
            self.assertIn("Armor Level III", config)
            self.assertEqual(info["no_break_spaces_replaced"], 2)
            self.assertEqual(json.loads((project / "release.json").read_text())["pilot_build_id"], "build")

    def test_split_keeps_every_check_in_order(self):
        checks = [["CfgAmmo", f"R{index}", [f"R{index}"], [["hit", "number", index]]] for index in range(50)]
        parts = split(checks, 200)
        self.assertGreater(len(parts), 1)
        self.assertEqual([check for part in parts for check in part], checks)

    def test_part_summary_must_cover_expected_fields(self):
        manifest = {"build_id": "build", "parts": [{"part": 1, "classes": 2, "fields": 10}, {"part": 2, "classes": 1, "fields": 5}]}
        begin = ["BEGIN_PILOT", 2, "build", 2, 2, 1, ["Arma 3"], []]
        self.assertTrue(validate_part([begin, ["END_PILOT", 2, "build", 2, 2, 1, 5, 0, 0]], manifest, 2)["passed"])
        with self.assertRaises(ValueError):
            validate_part([begin, ["END_PILOT", 2, "build", 2, 2, 1, 4, 0, 0]], manifest, 2)
        failure = ["FAILURE", "R", ["hit"], 1, 2]
        self.assertFalse(validate_part([begin, failure, ["END_PILOT", 2, "build", 2, 3, 1, 5, 1, 1]], manifest, 2)["passed"])


if __name__ == "__main__":
    unittest.main()
