import csv
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from build_query_db import build, number
from make_example_chart import render


def fixture(root):
    data, proposal, audit = (root / name for name in ("data-recovered", "proposal", "audit"))
    for folder in (data, proposal, audit):
        folder.mkdir()
    def record(section, name, props, addons=None):
        return {"section": section, "classname": name, "properties": props,
                "sourceAddons": addons or ["custom"], "ancestry": [name]}
    head = record("CfgWeapons", "Helmet", {"scope": "2s", "displayName": "Helmet", "ItemInfo": {
        "mass": 30, "HitpointsProtectionInfo": {"Head": {"hitpointName": "HitHead", "armor": "28 + 3", "passThrough": .5}}}},
        ["A3_Characters_F", "compatibility_override"])
    uniform = record("CfgWeapons", "Uniform", {"scope": 2, "ItemInfo": {"type": 801, "mass": 40,
                     "uniformClass": "UNIT", "containerClass": "SUPPLY"}})
    missing = record("CfgWeapons", "MissingUniform", {"scope": 2, "ItemInfo": {"uniformClass": "missing"}})
    ammo = record("CfgAmmo", "rhs_ammo_test", {"simulation": "shotBullet", "hit": 9,
                  "caliber": .45, "typicalSpeed": 800}, ["rhs_c_ammo"])
    rows = [head, uniform, missing, ammo,
            record("CfgVehicles", "unit", {"armor": 2, "armorStructural": 3, "HitPoints": {
                "HitChest": {"armor": 1, "passThrough": .3}}}),
            record("CfgVehicles", "Supply", {"maximumLoad": 100}),
            record("CfgMagazines", "magazine", {"ammo": "RHS_AMMO_TEST", "count": 30, "initSpeed": 900})]
    counts = {section: sum(row["section"] == section for row in rows) for section in {row["section"] for row in rows}}
    gear = [dict(head, kind="headgear"), dict(uniform, kind="uniform"), dict(missing, kind="uniform")]
    for name, entries in (("configs.relevant.jsonl", rows), ("wearables.jsonl", gear)):
        (data / name).write_text("".join(json.dumps(row) + "\n" for row in entries), encoding="utf-8")
    (data / "summary.json").write_text(json.dumps({"status": "partial", "sections": counts,
        "run": "fixture", "missing_by_section": {"CfgWeapons": 5}}), encoding="utf-8")
    hashes = {name: hashlib.sha256((data / name).read_bytes()).hexdigest()
              for name in ("configs.relevant.jsonl", "wearables.jsonl")}
    (proposal / "summary.json").write_text(json.dumps({"source_sha256": hashes, "proposed_field_changes": 1,
        "anchors": 1, "coverage_rows": 2, "ammunition_mapping_rows": 1, "ammunition_families": 1,
        "ammunition_preservation_guards": 0, "ammunition_penetration_check_rows": 0, "helmet_preservation_guard_rows": 0, "wearable_target_rows": 1, "wearable_preservation_guard_rows": 1, "wearable_assessment": {"classes": {"uniform": 1}, "comparison_rows": 1, "unit_usage_rows": 1}}), encoding="utf-8")
    (proposal / "ammunition_families.json").write_text(json.dumps([{
        "code": "556x45", "cartridge": "5.56x45", "vanilla_anchor": "rhs_ammo_test", "rhs_anchor": "rhs_ammo_test",
        "vanilla_coefficient": 9/800, "rhs_coefficient": 9/800, "hit_multiplier": 1,
        "target_hit": 10, "target_caliber": .45, "target_typical_speed": 800, "assumption": "fixture"}]), encoding="utf-8")
    (proposal / "ammunition_mapping.json").write_text(json.dumps([{
        "classname": "rhs_ammo_test", "cartridge_code": "556x45", "role": "generic_ball", "tracer_name_flag": False,
        "status": "proposed_change", "basis": "fixture", "reference_class": "rhs_ammo_test", "hit_multiplier": 1,
        "proposed": {"hit": 10, "caliber": .45, "typicalSpeed": 800}, "reason": "fixture"}]), encoding="utf-8")
    (proposal / "ammunition_preservation_guards.json").write_text("[]", encoding="utf-8")
    (proposal / "wearable_assessments.json").write_text(json.dumps([{
        "classname": "Uniform", "role": "ordinary_clothing", "status": "review", "basis": "fixture", "profile_id": "uniform_profile",
        "candidate_references": ["Uniform"], "matching_references": [], "flags": ["shared_unit_or_descendants"],
        "unit_class": "unit", "shared_uniform_count": 1, "unit_descendant_count": 0, "declared_wearer_count": 0,
        "reason": "fixture"}]), encoding="utf-8")
    (proposal / "wearable_comparisons.json").write_text(json.dumps([{
        "classname": "Uniform", "reference_class": "Uniform", "path": ["item", "armor"],
        "current_present": False, "reference_present": True, "current": None, "reference": 0}]), encoding="utf-8")
    (proposal / "uniform_unit_usage.json").write_text(json.dumps([{
        "unit_class": "unit", "resolved": True, "uniforms": ["Uniform"], "descendants": [], "declared_wearers": []}]), encoding="utf-8")
    (proposal / "wearable_targets.json").write_text(json.dumps([{
        "classname": "Uniform", "status": "review", "reference_class": "Uniform", "patch_section": "CfgVehicles",
        "patch_class": "unit", "field_changes": 0, "held_fields": [], "notes": ["fixture"], "reason": "fixture"}]), encoding="utf-8")
    (proposal / "wearable_preservation_guards.json").write_text(json.dumps([{
        "section": "CfgVehicles", "classname": "unit", "path": ["armor"], "present": True,
        "retain": 2, "changed_ancestors": ["parent"], "status": "retain_observed_field"}]), encoding="utf-8")
    (proposal / "ammunition_penetration_checks.json").write_text("[]", encoding="utf-8")
    (proposal / "helmet_preservation_guards.json").write_text("[]", encoding="utf-8")
    change = {"section": "CfgAmmo", "classname": "rhs_ammo_test", "kind": "projectile", "path": ["hit"],
              "old": 9, "proposed": 10, "rule": "test", "anchors": ["rhs_ammo_test"],
              "confidence": "proposal", "reason": "test"}
    (proposal / "change_ledger.json").write_text(json.dumps([change]), encoding="utf-8")
    (proposal / "anchors.json").write_text(json.dumps([{"section": "CfgAmmo", "classname": "rhs_ammo_test",
        "kind": "projectile", "role": "test", "cartridge": "test"}]), encoding="utf-8")
    with (proposal / "coverage.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["section", "classname", "status", "rule", "reason"])
        writer.writerow(["CfgAmmo", "rhs_ammo_test", "proposed_change", "test", "test"])
        writer.writerow(["CfgWeapons", "Uniform", "review", "test", "test"])
    (audit / "profiles.json").write_text(json.dumps([{"id": "profile", "kind": "headgear",
        "protection": {"armor": "28 + 3"}, "classes": ["Helmet"]}]), encoding="utf-8")
    (audit / "bullet_profiles.json").write_text("[]", encoding="utf-8")


class QueryDatabaseTests(unittest.TestCase):
    def test_numeric_policy_never_coerces_unknowns_to_zero(self):
        for value in (None, "28 + 3", "true", "2s", True, float("inf")):
            self.assertIsNone(number(value))
        self.assertEqual(number(0), 0)
        self.assertEqual(number(.5), .5)

    def test_views_links_provenance_raw_values_and_csv_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            build(root)
            with closing(sqlite3.connect(root / "equipment.sqlite")) as db:
                db.row_factory = sqlite3.Row
                head = db.execute("SELECT * FROM v_headgear_comparison").fetchone()
                self.assertIsNone(head["scope"])
                self.assertIsNone(head["armor"])
                self.assertEqual(json.loads(head["armor_raw_json"]), "28 + 3")
                self.assertEqual(head["value_status"], "contains_text_expression")
                self.assertEqual(head["family"], "Vanilla class")
                self.assertEqual(db.execute("SELECT count(*) FROM v_source_addons WHERE classname='Helmet'").fetchone()[0], 2)
                unit = db.execute("SELECT * FROM v_wearable_protection WHERE classname='Uniform'").fetchone()
                self.assertEqual((unit["region_context"], unit["armor"], unit["unit_base_armor"]), ("unit", 1, 2))
                self.assertEqual(unit["maximum_load"], 100)
                unknown = db.execute("SELECT * FROM v_wearable_protection WHERE classname='MissingUniform'").fetchone()
                self.assertEqual(unknown["value_status"], "unresolved_uniform")
                self.assertIsNone(unknown["armor"])
                bullet = db.execute("SELECT * FROM v_bullets").fetchone()
                self.assertEqual((bullet["penetration_multiplier"], bullet["magazine_count"]), (.45, 1))
                assessed = db.execute("SELECT * FROM v_wearable_assessments").fetchone()
                self.assertEqual((assessed["classname"], assessed["mass"], assessed["maximum_load"]), ("Uniform", 40, 100))
                target = db.execute("SELECT * FROM v_wearable_targets").fetchone()
                self.assertEqual((target["classname"], target["patch_section"], target["patch_class"]), ("Uniform", "CfgVehicles", "unit"))
                guard = db.execute("SELECT * FROM v_wearable_preservation_guards").fetchone()
                self.assertEqual((guard["section"], guard["classname"], guard["present"]), ("CfgVehicles", "unit", 1))
                self.assertEqual(json.loads(guard["retained_json"]), 2)
                pair = db.execute("SELECT * FROM v_wearable_reference_pairs").fetchone()
                self.assertEqual((pair["mass"], pair["reference_mass"], pair["differing_fields"]), (40, 40, 1))
                compared = db.execute("SELECT * FROM v_wearable_comparisons").fetchone()
                self.assertEqual((compared["current_present"], compared["reference_present"]), (0, 1))
                self.assertIsNone(compared["current_number"])
                self.assertEqual(compared["reference_number"], 0)
                self.assertEqual(db.execute("SELECT uniform_count FROM v_uniform_unit_usage").fetchone()[0], 1)
                change = db.execute("SELECT * FROM v_proposed_changes").fetchone()
                self.assertEqual((change["old_number"], change["proposed_number"], change["delta"]), (9, 10, 1))
                mapped = db.execute("SELECT * FROM v_ammunition_mapping").fetchone()
                self.assertEqual((mapped["hit"], mapped["proposed_hit"]), (9, 10))
                self.assertEqual(mapped["mapping_status"], "proposed_change")
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            with (root / "chart-data" / "headgear.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["armor"], "")

    def test_stale_inputs_cannot_replace_existing_database(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            build(root)
            original = hashlib.sha256((root / "equipment.sqlite").read_bytes()).digest()
            with (root / "data-recovered" / "wearables.jsonl").open("a", encoding="utf-8") as stream:
                stream.write("\n")
            with self.assertRaisesRegex(ValueError, "stale"):
                build(root)
            self.assertEqual(hashlib.sha256((root / "equipment.sqlite").read_bytes()).digest(), original)
            self.assertEqual(list(root.glob("*.building")), [])

    def test_chart_is_read_only_and_embeds_class_names_safely(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            build(root)
            database = root / "equipment.sqlite"
            with closing(sqlite3.connect(database)) as db:
                db.execute("UPDATE configs SET classname=?,scope=2 WHERE classname='Helmet'", ('helmet</script>__QUERY__',))
                db.execute("UPDATE armor_regions SET armor=6 WHERE context='item'")
                db.commit()
            before = hashlib.sha256(database.read_bytes()).digest()
            result = render(database, root / "chart.html")
            self.assertEqual(result["classes"], 1)
            self.assertEqual(hashlib.sha256(database.read_bytes()).digest(), before)
            page = (root / "chart.html").read_text(encoding="utf-8")
            self.assertIn(r'helmet\u003c/script>__QUERY__', page)
            self.assertNotIn('helmet</script>', page)


if __name__ == "__main__":
    unittest.main()
