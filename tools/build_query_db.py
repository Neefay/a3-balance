"""Build a local SQLite query database and flat chart datasets, using only Python's standard library."""
from collections import Counter
from contextlib import closing
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

from extract_rpt import canonical, get


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value_json TEXT NOT NULL CHECK(json_valid(value_json)));
CREATE TABLE configs (
 id INTEGER PRIMARY KEY, section TEXT NOT NULL COLLATE NOCASE,
 classname TEXT NOT NULL COLLATE NOCASE, display_name TEXT, scope REAL, scope_raw_json TEXT,
 family TEXT NOT NULL, base_armor REAL, armor_structural REAL, maximum_load REAL,
 source_addons_json TEXT NOT NULL, ancestry_json TEXT NOT NULL, properties_json TEXT NOT NULL,
 UNIQUE(section, classname));
CREATE TABLE wearables (
 class_id INTEGER PRIMARY KEY REFERENCES configs(id), kind TEXT NOT NULL,
 mass REAL, mass_raw_json TEXT, uniform_class TEXT, unit_class_id INTEGER REFERENCES configs(id),
 container_class TEXT, container_class_id INTEGER REFERENCES configs(id),
 legacy_armor_raw_json TEXT, legacy_pass_through_raw_json TEXT);
CREATE TABLE armor_regions (
 id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES configs(id),
 context TEXT NOT NULL, region TEXT NOT NULL, hitpoint TEXT,
 armor REAL, armor_raw_json TEXT NOT NULL, pass_through REAL, pass_through_raw_json TEXT NOT NULL,
 explosion_shielding REAL, properties_json TEXT NOT NULL);
CREATE TABLE projectiles (
 class_id INTEGER PRIMARY KEY REFERENCES configs(id), simulation TEXT,
 hit REAL, caliber REAL, typical_speed REAL, air_friction REAL, explosive REAL,
 indirect_hit REAL, indirect_hit_range REAL, ace_caliber_mm REAL, ace_bullet_mass_g REAL);
CREATE TABLE magazines (
 class_id INTEGER PRIMARY KEY REFERENCES configs(id), ammo_classname TEXT,
 projectile_class_id INTEGER REFERENCES projectiles(class_id), rounds REAL, init_speed REAL, mass REAL);
CREATE TABLE changes (
 id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES configs(id), kind TEXT,
 path_json TEXT NOT NULL, field TEXT NOT NULL, old_json TEXT NOT NULL, proposed_json TEXT NOT NULL,
 old_number REAL, proposed_number REAL, rule TEXT, anchors_json TEXT, confidence TEXT, reason TEXT);
CREATE TABLE anchors (
 id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES configs(id),
 kind TEXT, role TEXT, cartridge TEXT, details_json TEXT NOT NULL);
CREATE TABLE coverage (
 class_id INTEGER PRIMARY KEY REFERENCES configs(id), status TEXT, rule TEXT, reason TEXT);
CREATE TABLE ammunition_families (
 code TEXT PRIMARY KEY, cartridge TEXT NOT NULL,
 vanilla_anchor_id INTEGER NOT NULL REFERENCES projectiles(class_id),
 rhs_anchor_id INTEGER NOT NULL REFERENCES projectiles(class_id),
 vanilla_coefficient REAL, rhs_coefficient REAL, hit_multiplier REAL,
 target_hit REAL, target_caliber REAL, target_typical_speed REAL, assumption TEXT);
CREATE TABLE ammunition_mapping (
 class_id INTEGER PRIMARY KEY REFERENCES projectiles(class_id), cartridge_code TEXT,
 role TEXT, tracer_name_flag INTEGER NOT NULL, status TEXT, basis TEXT,
 reference_class_id INTEGER REFERENCES projectiles(class_id), hit_multiplier REAL,
 proposed_hit REAL, proposed_caliber REAL, proposed_typical_speed REAL, reason TEXT);
CREATE TABLE ammunition_preservation_guards (
 class_id INTEGER PRIMARY KEY REFERENCES projectiles(class_id), changed_ancestors_json TEXT,
 retained_values_json TEXT, reason TEXT);
CREATE TABLE wearable_assessments (
 class_id INTEGER PRIMARY KEY REFERENCES wearables(class_id), role TEXT NOT NULL, status TEXT NOT NULL,
 basis TEXT, profile_id TEXT NOT NULL, candidate_references_json TEXT NOT NULL, matching_references_json TEXT NOT NULL,
 flags_json TEXT NOT NULL, unit_class TEXT, shared_uniform_count INTEGER, unit_descendant_count INTEGER,
 declared_wearer_count INTEGER, reason TEXT);
CREATE TABLE wearable_comparisons (
 id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES wearable_assessments(class_id),
 reference_class_id INTEGER NOT NULL REFERENCES wearables(class_id), path_json TEXT NOT NULL,
 current_present INTEGER NOT NULL, reference_present INTEGER NOT NULL,
 current_json TEXT NOT NULL, reference_json TEXT NOT NULL, current_number REAL, reference_number REAL);
CREATE TABLE uniform_unit_usage (
 unit_class TEXT PRIMARY KEY COLLATE NOCASE, unit_class_id INTEGER REFERENCES configs(id),
 resolved INTEGER NOT NULL, uniforms_json TEXT NOT NULL, descendants_json TEXT NOT NULL, declared_wearers_json TEXT NOT NULL);
CREATE TABLE wearable_targets (
 class_id INTEGER PRIMARY KEY REFERENCES wearable_assessments(class_id), status TEXT NOT NULL,
 reference_class_id INTEGER REFERENCES wearables(class_id), patch_class_id INTEGER REFERENCES configs(id),
 field_changes INTEGER NOT NULL, held_fields_json TEXT NOT NULL, notes_json TEXT NOT NULL, reason TEXT);
CREATE TABLE wearable_preservation_guards (
 id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES configs(id), path_json TEXT NOT NULL,
 present INTEGER NOT NULL, retained_json TEXT NOT NULL, changed_ancestors_json TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE ammunition_penetration_checks (
 class_id INTEGER PRIMARY KEY REFERENCES projectiles(class_id), cartridge TEXT, role TEXT,
 observed_penetration_json TEXT NOT NULL, observed_penetration REAL, candidate_ball_penetration REAL,
 expectation TEXT, status TEXT);
CREATE TABLE helmet_preservation_guards (
 id INTEGER PRIMARY KEY, class_id INTEGER NOT NULL REFERENCES configs(id), path_json TEXT NOT NULL,
 present INTEGER NOT NULL, retained_json TEXT NOT NULL, changed_ancestors_json TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE profiles (
 type TEXT NOT NULL, id TEXT NOT NULL, kind TEXT, properties_json TEXT NOT NULL,
 PRIMARY KEY(type, id));
CREATE TABLE profile_members (
 type TEXT NOT NULL, profile_id TEXT NOT NULL, class_id INTEGER NOT NULL REFERENCES configs(id),
 PRIMARY KEY(type, profile_id, class_id), FOREIGN KEY(type, profile_id) REFERENCES profiles(type, id));
CREATE INDEX wearable_comparison_class ON wearable_comparisons(class_id,reference_class_id);
CREATE INDEX configs_section_scope ON configs(section, scope);
CREATE INDEX configs_family ON configs(family);
CREATE INDEX armor_class_context ON armor_regions(class_id, context);
CREATE INDEX projectiles_simulation ON projectiles(simulation);
CREATE INDEX magazine_projectile ON magazines(projectile_class_id);
CREATE INDEX changes_class ON changes(class_id);
CREATE INDEX profile_class ON profile_members(class_id);

CREATE VIEW v_ammunition_penetration_checks AS
 SELECT c.classname, p.* FROM ammunition_penetration_checks p JOIN configs c ON c.id=p.class_id;
CREATE VIEW v_helmet_preservation_guards AS
 SELECT c.classname,g.path_json,g.present,g.retained_json,g.changed_ancestors_json,g.status
 FROM helmet_preservation_guards g JOIN configs c ON c.id=g.class_id;
CREATE VIEW v_wearable_targets AS
 SELECT w.*, a.role, t.status AS target_status, r.classname AS reference_class,
        p.section AS patch_section, p.classname AS patch_class, t.field_changes,
        t.held_fields_json, t.notes_json, t.reason
 FROM wearable_targets t JOIN v_wearables w ON w.class_id=t.class_id
 JOIN wearable_assessments a ON a.class_id=t.class_id
 LEFT JOIN configs r ON r.id=t.reference_class_id LEFT JOIN configs p ON p.id=t.patch_class_id;
CREATE VIEW v_wearable_preservation_guards AS
 SELECT c.section,c.classname,g.path_json,g.present,g.retained_json,g.changed_ancestors_json,g.status
 FROM wearable_preservation_guards g JOIN configs c ON c.id=g.class_id;
CREATE VIEW v_wearable_assessments AS
 SELECT w.*, a.role, a.status AS assessment_status, a.basis AS classification_basis,
        a.profile_id, a.candidate_references_json, a.matching_references_json, a.flags_json,
        a.shared_uniform_count, a.unit_descendant_count, a.declared_wearer_count, a.reason
 FROM v_wearables w JOIN wearable_assessments a ON a.class_id=w.class_id;
CREATE VIEW v_wearable_reference_pairs AS
 SELECT a.classname, a.kind, a.role, a.family, a.scope, a.assessment_status,
        r.classname AS reference_class, a.mass, r.mass AS reference_mass,
        a.maximum_load, r.maximum_load AS reference_maximum_load,
        r.mass-a.mass AS reference_mass_delta,
        r.maximum_load-a.maximum_load AS reference_capacity_delta,
        CASE WHEN a.unit_link_status='unresolved' THEN NULL ELSE
        (SELECT count(*) FROM wearable_comparisons d
         WHERE d.class_id=a.class_id AND d.reference_class_id=r.class_id) END AS differing_fields
 FROM v_wearable_assessments a, json_each(a.candidate_references_json) candidate
 JOIN configs reference ON reference.section='CfgWeapons' AND reference.classname=candidate.value COLLATE NOCASE
 JOIN v_wearables r ON r.class_id=reference.id AND r.kind=a.kind;
CREATE VIEW v_wearable_comparisons AS
 SELECT c.classname, a.kind, a.role, c.family, c.scope, r.classname AS reference_class,
        d.path_json, d.current_present, d.reference_present, d.current_json, d.reference_json,
        d.current_number, d.reference_number, d.reference_number-d.current_number AS reference_delta
 FROM wearable_comparisons d JOIN configs r ON r.id=d.reference_class_id
 JOIN configs c ON c.id=d.class_id JOIN v_wearable_assessments a ON a.class_id=d.class_id;
CREATE VIEW v_uniform_unit_usage AS
 SELECT u.*, json_array_length(uniforms_json) AS uniform_count,
        json_array_length(descendants_json) AS descendant_count,
        json_array_length(declared_wearers_json) AS declared_wearer_count
 FROM uniform_unit_usage u;
CREATE VIEW v_source_addons AS
 SELECT c.id AS class_id, c.section, c.classname, j.value AS addon
 FROM configs c, json_each(c.source_addons_json) j;
CREATE VIEW v_ancestry AS
 SELECT c.id AS class_id, c.section, c.classname, CAST(j.key AS INTEGER) AS depth, j.value AS ancestor
 FROM configs c, json_each(c.ancestry_json) j;
CREATE VIEW v_wearables AS
 SELECT c.id AS class_id, c.classname, c.display_name, w.kind, c.family, c.scope, c.scope_raw_json,
        w.mass, w.mass_raw_json, w.container_class, container.maximum_load,
        w.uniform_class, w.unit_class_id, unit.base_armor AS unit_base_armor,
        unit.armor_structural AS unit_armor_structural,
        CASE WHEN w.kind <> 'uniform' THEN 'not_applicable'
             WHEN w.unit_class_id IS NULL THEN 'unresolved' ELSE 'resolved' END AS unit_link_status,
        w.legacy_armor_raw_json, w.legacy_pass_through_raw_json, c.source_addons_json
 FROM wearables w JOIN configs c ON c.id=w.class_id
 LEFT JOIN configs unit ON unit.id=w.unit_class_id
 LEFT JOIN configs container ON container.id=w.container_class_id;
CREATE VIEW v_wearable_protection AS
 SELECT w.*, a.context AS region_context, a.region, a.hitpoint, a.armor, a.armor_raw_json,
        a.pass_through, a.pass_through_raw_json, a.explosion_shielding,
        source.classname AS protection_source_class,
        CASE WHEN w.unit_link_status='unresolved' THEN 'unresolved_uniform'
             WHEN a.id IS NULL THEN 'no_exported_region'
             WHEN json_type(a.armor_raw_json)='text' OR json_type(a.pass_through_raw_json)='text'
                  THEN 'contains_text_expression' ELSE 'exported_numeric_or_missing' END AS value_status
 FROM v_wearables w
 LEFT JOIN armor_regions a
   ON a.class_id=CASE WHEN w.kind='uniform' THEN w.unit_class_id ELSE w.class_id END
   AND a.context=CASE WHEN w.kind='uniform' THEN 'unit' ELSE 'item' END
 LEFT JOIN configs source ON source.id=a.class_id;
CREATE VIEW v_headgear_comparison AS
 SELECT * FROM v_wearable_protection
 WHERE kind='headgear' AND region_context='item' AND lower(hitpoint)='hithead';
CREATE VIEW v_ammunition AS
 SELECT c.id AS class_id, c.classname, c.display_name, c.family,
        p.simulation, p.hit, p.caliber AS penetration_multiplier, p.typical_speed,
        p.air_friction, p.explosive, p.indirect_hit, p.indirect_hit_range,
        p.ace_caliber_mm, p.ace_bullet_mass_g,
        (SELECT count(*) FROM magazines m WHERE m.projectile_class_id=p.class_id) AS magazine_count,
        c.source_addons_json
 FROM projectiles p JOIN configs c ON c.id=p.class_id;
CREATE VIEW v_bullets AS SELECT * FROM v_ammunition WHERE simulation='shotBullet';
CREATE VIEW v_proposed_changes AS
 SELECT ch.id AS change_id, c.section, c.classname, c.display_name, c.family, c.scope, ch.kind,
        ch.field, ch.path_json, ch.old_number, ch.proposed_number,
        ch.proposed_number-ch.old_number AS delta, ch.old_json, ch.proposed_json,
        ch.rule, ch.confidence, ch.reason, ch.anchors_json
 FROM changes ch JOIN configs c ON c.id=ch.class_id;
CREATE VIEW v_anchor_regions AS
 SELECT c.classname, c.display_name, c.family, a.kind, a.role, a.cartridge,
        r.region, r.hitpoint, r.armor, r.armor_raw_json, r.pass_through, r.pass_through_raw_json,
        p.hit, p.caliber, p.typical_speed, p.air_friction
 FROM anchors a JOIN configs c ON c.id=a.class_id
 LEFT JOIN wearables w ON w.class_id=a.class_id
 LEFT JOIN armor_regions r ON r.class_id=CASE WHEN a.kind='uniform' THEN w.unit_class_id ELSE a.class_id END
 AND r.context=CASE WHEN a.kind='uniform' THEN 'unit' ELSE 'item' END
 LEFT JOIN projectiles p ON p.class_id=a.class_id;
CREATE VIEW v_profile_counts AS
 SELECT p.type, p.id AS profile_id, p.kind, c.family, count(*) AS class_count,
        sum(CASE WHEN c.scope=2 THEN 1 ELSE 0 END) AS public_class_count
 FROM profiles p JOIN profile_members m ON m.type=p.type AND m.profile_id=p.id
 JOIN configs c ON c.id=m.class_id GROUP BY p.type, p.id, p.kind, c.family;
CREATE VIEW v_ammunition_mapping AS
 SELECT p.*, m.cartridge_code, f.cartridge, m.role, m.tracer_name_flag, m.status AS mapping_status,
        m.basis AS mapping_basis, reference.classname AS reference_class, m.hit_multiplier,
        m.proposed_hit, m.proposed_caliber AS proposed_penetration_multiplier, m.proposed_typical_speed,
        p.hit/NULLIF(p.typical_speed,0) AS current_kinetic_coefficient,
        m.proposed_hit/NULLIF(m.proposed_typical_speed,0) AS proposed_kinetic_coefficient, m.reason
 FROM v_bullets p JOIN ammunition_mapping m ON m.class_id=p.class_id
 LEFT JOIN ammunition_families f ON f.code=m.cartridge_code
 LEFT JOIN configs reference ON reference.id=m.reference_class_id;
CREATE VIEW v_ammunition_family_scale AS
 SELECT f.code, f.cartridge, v.classname AS vanilla_anchor, r.classname AS rhs_anchor,
        f.vanilla_coefficient, f.rhs_coefficient, f.hit_multiplier,
        f.target_hit, f.target_caliber AS target_penetration_multiplier, f.target_typical_speed, f.assumption
 FROM ammunition_families f JOIN configs v ON v.id=f.vanilla_anchor_id JOIN configs r ON r.id=f.rhs_anchor_id;
CREATE VIEW v_ammunition_preservation_guards AS
 SELECT c.classname, p.simulation, p.hit AS retained_hit, p.caliber AS retained_penetration_multiplier,
        p.typical_speed AS retained_typical_speed, g.changed_ancestors_json, g.retained_values_json, g.reason
 FROM ammunition_preservation_guards g JOIN configs c ON c.id=g.class_id JOIN projectiles p ON p.class_id=g.class_id;
"""


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def family(row):
    addons = [name.lower() for name in row["sourceAddons"]]
    if row["classname"].lower().startswith("rhs") and any(name.startswith("rhs") for name in addons):
        return "RHS"
    if any(name.startswith("a3_") for name in addons):
        return "Vanilla class"
    return "Other"


def regions(db, class_id, context, tree):
    for name, props in tree.items():
        if not isinstance(props, dict):
            continue
        armor, through = get(props, "armor"), get(props, "passThrough")
        db.execute("INSERT INTO armor_regions(class_id,context,region,hitpoint,armor,armor_raw_json,"
                   "pass_through,pass_through_raw_json,explosion_shielding,properties_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (class_id, context, name, get(props, "hitpointName", name if context == "unit" else None),
                    number(armor), canonical(armor), number(through), canonical(through),
                    number(get(props, "explosionShielding")), canonical(props)))


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def populate(db, root):
    data, proposal, audit = root / "data-recovered", root / "proposal", root / "audit"
    extraction, plan = load_json(data / "summary.json"), load_json(proposal / "summary.json")
    if extraction["status"] not in ("complete", "partial"):
        raise ValueError("Extraction has not finished")
    for name, expected in plan["source_sha256"].items():
        with (data / name).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError(f"Proposal is stale relative to {name}; regenerate it first")
    db.executescript(SCHEMA)
    for key, value in {"schema_version": 5, "extraction": extraction, "proposal": plan,
                       "dataset_scope": "All recovered classes with properties from configs.relevant.jsonl; the unpruned archive remains separate.",
                       "family_definition": "Reference grouping from class names/source addons, not sole mod ownership.",
                       "numeric_policy": "Text expressions and missing values become SQL NULL in numeric columns; raw JSON retains their original types."}.items():
        db.execute("INSERT INTO metadata VALUES(?,?)", (key, canonical(value)))
    ids, counts = {}, Counter()
    pending_magazines = []
    with (data / "configs.relevant.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            props, section = row["properties"], row["section"]
            cursor = db.execute("INSERT INTO configs(section,classname,display_name,scope,scope_raw_json,family,"
                                "base_armor,armor_structural,maximum_load,source_addons_json,ancestry_json,properties_json)"
                                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
                section, row["classname"], get(props, "displayName"), number(get(props, "scope")), canonical(get(props, "scope")),
                family(row), number(get(props, "armor")), number(get(props, "armorStructural")), number(get(props, "maximumLoad")),
                canonical(row["sourceAddons"]), canonical(row["ancestry"]), canonical(props)))
            class_id = cursor.lastrowid
            ids[(section.lower(), row["classname"].lower())] = class_id
            counts[section] += 1
            if section == "CfgVehicles":
                regions(db, class_id, "unit", get(props, "HitPoints", {}))
            elif section == "CfgAmmo":
                values = [number(get(props, field)) for field in ("hit", "caliber", "typicalSpeed", "airFriction", "explosive",
                          "indirectHit", "indirectHitRange", "ACE_caliber", "ACE_bulletMass")]
                db.execute("INSERT INTO projectiles VALUES(?,?,?,?,?,?,?,?,?,?,?)", [class_id, get(props, "simulation")] + values)
            elif section == "CfgMagazines":
                pending_magazines.append((class_id, get(props, "ammo", ""), number(get(props, "count")),
                                          number(get(props, "initSpeed")), number(get(props, "mass"))))
    if dict(counts) != extraction["sections"]:
        raise ValueError(f"Class counts differ from extraction summary: {dict(counts)}")
    def resolve(section, name, required=False):
        found = ids.get((section.lower(), (name or "").lower()))
        if required and found is None:
            raise ValueError(f"Missing class referenced by analysis: {section}/{name}")
        return found
    for class_id, name, rounds, speed, mass in pending_magazines:
        db.execute("INSERT INTO magazines VALUES(?,?,?,?,?,?)",
                   (class_id, name, resolve("CfgAmmo", name), rounds, speed, mass))
    with (data / "wearables.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            class_id = resolve(row["section"], row["classname"], True)
            info = row["properties"] if row["kind"] == "glasses" else get(row["properties"], "ItemInfo", {})
            unit, container, mass = get(info, "uniformClass"), get(info, "containerClass"), get(info, "mass")
            db.execute("INSERT INTO wearables VALUES(?,?,?,?,?,?,?,?,?,?)", (
                class_id, row["kind"], number(mass), canonical(mass), unit, resolve("CfgVehicles", unit),
                container, resolve("CfgVehicles", container), canonical(get(info, "armor")), canonical(get(info, "passThrough"))))
            regions(db, class_id, "item", get(info, "HitpointsProtectionInfo", {}))
    for row in load_json(proposal / "change_ledger.json"):
        class_id = resolve(row["section"], row["classname"], True)
        db.execute("INSERT INTO changes(class_id,kind,path_json,field,old_json,proposed_json,old_number,proposed_number,"
                   "rule,anchors_json,confidence,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
            class_id, row["kind"], canonical(row["path"]), row["path"][-1], canonical(row["old"]), canonical(row["proposed"]),
            number(row["old"]), number(row["proposed"]), row["rule"], canonical(row["anchors"]), row["confidence"], row["reason"]))
    for row in load_json(proposal / "anchors.json"):
        db.execute("INSERT INTO anchors(class_id,kind,role,cartridge,details_json) VALUES(?,?,?,?,?)", (
            resolve(row["section"], row["classname"], True), row["kind"], row["role"], row.get("cartridge"), canonical(row)))
    with (proposal / "coverage.csv").open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            db.execute("INSERT INTO coverage VALUES(?,?,?,?)", (
                resolve(row["section"], row["classname"], True), row["status"], row["rule"], row["reason"]))
    for row in load_json(proposal / "ammunition_families.json"):
        db.execute("INSERT INTO ammunition_families VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            row["code"], row["cartridge"], resolve("CfgAmmo", row["vanilla_anchor"], True),
            resolve("CfgAmmo", row["rhs_anchor"], True), row["vanilla_coefficient"], row["rhs_coefficient"],
            row["hit_multiplier"], row["target_hit"], row["target_caliber"], row["target_typical_speed"], row["assumption"]))
    for row in load_json(proposal / "ammunition_mapping.json"):
        target = row["proposed"] or {}
        db.execute("INSERT INTO ammunition_mapping VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
            resolve("CfgAmmo", row["classname"], True), row["cartridge_code"], row["role"], int(row["tracer_name_flag"]),
            row["status"], row["basis"], resolve("CfgAmmo", row["reference_class"], bool(row["reference_class"])), row["hit_multiplier"],
            number(target.get("hit")), number(target.get("caliber")), number(target.get("typicalSpeed")), row["reason"]))
    for row in load_json(proposal / "ammunition_preservation_guards.json"):
        db.execute("INSERT INTO ammunition_preservation_guards VALUES(?,?,?,?)", (
            resolve("CfgAmmo", row["classname"], True), canonical(row["changed_ancestors"]), canonical(row["retain"]), row["reason"]))
    for row in load_json(proposal / "wearable_assessments.json"):
        db.execute("INSERT INTO wearable_assessments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            resolve("CfgWeapons", row["classname"], True), row["role"], row["status"], row["basis"], row["profile_id"],
            canonical(row["candidate_references"]), canonical(row["matching_references"]), canonical(row["flags"]),
            row["unit_class"], row["shared_uniform_count"], row["unit_descendant_count"], row["declared_wearer_count"], row["reason"]))
    for row in load_json(proposal / "wearable_comparisons.json"):
        db.execute("INSERT INTO wearable_comparisons(class_id,reference_class_id,path_json,current_present,reference_present,"
                   "current_json,reference_json,current_number,reference_number) VALUES(?,?,?,?,?,?,?,?,?)", (
            resolve("CfgWeapons", row["classname"], True), resolve("CfgWeapons", row["reference_class"], True),
            canonical(row["path"]), int(row["current_present"]), int(row["reference_present"]),
            canonical(row["current"]), canonical(row["reference"]), number(row["current"]), number(row["reference"])))
    for row in load_json(proposal / "uniform_unit_usage.json"):
        db.execute("INSERT INTO uniform_unit_usage VALUES(?,?,?,?,?,?)", (
            row["unit_class"], resolve("CfgVehicles", row["unit_class"], row["resolved"]), int(row["resolved"]),
            canonical(row["uniforms"]), canonical(row["descendants"]), canonical(row["declared_wearers"])))
    for row in load_json(proposal / "wearable_targets.json"):
        db.execute("INSERT INTO wearable_targets VALUES(?,?,?,?,?,?,?,?)", (
            resolve("CfgWeapons", row["classname"], True), row["status"],
            resolve("CfgWeapons", row["reference_class"], bool(row["reference_class"])),
            resolve(row["patch_section"], row["patch_class"], True) if row["patch_class"] else None,
            row["field_changes"], canonical(row["held_fields"]), canonical(row["notes"]), row["reason"]))
    for row in load_json(proposal / "wearable_preservation_guards.json"):
        db.execute("INSERT INTO wearable_preservation_guards(class_id,path_json,present,retained_json,changed_ancestors_json,status) VALUES(?,?,?,?,?,?)", (
            resolve(row["section"], row["classname"], True), canonical(row["path"]), int(row["present"]),
            canonical(row["retain"]), canonical(row["changed_ancestors"]), row["status"]))
    for row in load_json(proposal / "ammunition_penetration_checks.json"):
        db.execute("INSERT INTO ammunition_penetration_checks VALUES(?,?,?,?,?,?,?,?)", (
            resolve("CfgAmmo", row["classname"], True), row["cartridge"], row["role"],
            canonical(row["observed_penetration"]), number(row["observed_penetration"]),
            number(row["candidate_ball_penetration"]), row["expectation"], row["status"]))
    for row in load_json(proposal / "helmet_preservation_guards.json"):
        db.execute("INSERT INTO helmet_preservation_guards(class_id,path_json,present,retained_json,changed_ancestors_json,status) VALUES(?,?,?,?,?,?)", (
            resolve(row["section"], row["classname"], True), canonical(row["path"]), int(row["present"]),
            canonical(row["retain"]), canonical(row["changed_ancestors"]), row["status"]))
    for profile_type, filename in (("protection", "profiles.json"), ("bullet", "bullet_profiles.json")):
        for row in load_json(audit / filename):
            db.execute("INSERT INTO profiles VALUES(?,?,?,?)", (
                profile_type, row["id"], row.get("kind", "projectile"), canonical(row.get("protection", row.get("properties")))))
            for name in row["classes"]:
                section = "CfgAmmo" if profile_type == "bullet" else "CfgGlasses" if row["kind"] == "glasses" else "CfgWeapons"
                db.execute("INSERT INTO profile_members VALUES(?,?,?)", (profile_type, row["id"], resolve(section, name, True)))
    expected = {"changes": plan["proposed_field_changes"], "anchors": plan["anchors"], "coverage": plan["coverage_rows"],
                "ammunition_mapping": plan["ammunition_mapping_rows"], "ammunition_families": plan["ammunition_families"],
                "ammunition_preservation_guards": plan["ammunition_preservation_guards"]}
    assessed = plan["wearable_assessment"]
    expected.update(wearable_assessments=sum(assessed["classes"].values()),
                    wearable_comparisons=assessed["comparison_rows"], uniform_unit_usage=assessed["unit_usage_rows"])
    expected.update(wearable_targets=plan["wearable_target_rows"],
                    wearable_preservation_guards=plan["wearable_preservation_guard_rows"])
    expected.update(ammunition_penetration_checks=plan["ammunition_penetration_check_rows"],
                    helmet_preservation_guards=plan["helmet_preservation_guard_rows"])
    for table, count in expected.items():
        if db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] != count:
            raise ValueError(f"Imported {table} count differs from proposal summary")
    if db.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("Database contains invalid foreign-key references")
    if db.execute("SELECT count(*) FROM ammunition_mapping m JOIN coverage c ON c.class_id=m.class_id WHERE m.status<>c.status").fetchone()[0]:
        raise ValueError("Ammunition mapping and coverage statuses disagree")
    if db.execute("SELECT count(*) FROM wearable_assessments a JOIN coverage c ON c.class_id=a.class_id LEFT JOIN wearable_targets t ON t.class_id=a.class_id WHERE coalesce(t.status,a.status)<>c.status").fetchone()[0]:
        raise ValueError("Wearable assessment and coverage statuses disagree")
    if db.execute("SELECT count(*) FROM wearable_targets t WHERE t.field_changes>0 AND t.field_changes<>(SELECT count(*) FROM changes c WHERE c.class_id=t.patch_class_id)").fetchone()[0]:
        raise ValueError("Wearable target field counts differ from the change ledger")
    return counts


EXPORTS = {
    "ammunition_penetration_checks": "SELECT * FROM v_ammunition_penetration_checks ORDER BY status,cartridge,classname",
    "helmet_preservation_guards": "SELECT * FROM v_helmet_preservation_guards ORDER BY classname,path_json",
    "wearable_targets": "SELECT * FROM v_wearable_targets ORDER BY classname",
    "wearable_preservation_guards": "SELECT * FROM v_wearable_preservation_guards ORDER BY section,classname,path_json",
    "wearable_reference_pairs": "SELECT * FROM v_wearable_reference_pairs ORDER BY classname,reference_class",
    "vest_classifications": "SELECT * FROM v_wearable_assessments WHERE kind='vest' ORDER BY classname",
    "uniform_assessments": "SELECT * FROM v_wearable_assessments WHERE kind='uniform' ORDER BY classname",
    "wearable_comparisons": "SELECT * FROM v_wearable_comparisons ORDER BY classname,reference_class,path_json",
    "uniform_unit_usage": "SELECT * FROM v_uniform_unit_usage ORDER BY unit_class",
    "headgear": "SELECT * FROM v_headgear_comparison ORDER BY classname",
    "vest_regions": "SELECT * FROM v_wearable_protection WHERE kind='vest' ORDER BY classname,region",
    "ammunition": "SELECT * FROM v_ammunition ORDER BY classname",
    "proposed_changes": "SELECT * FROM v_proposed_changes ORDER BY classname,field",
    "profile_counts": "SELECT * FROM v_profile_counts ORDER BY type,kind,family,profile_id",
    "ammunition_mapping": "SELECT * FROM v_ammunition_mapping ORDER BY classname",
    "ammunition_family_scale": "SELECT * FROM v_ammunition_family_scale ORDER BY cartridge",
}


def export_csvs(database, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database)) as db:
        for name, sql in EXPORTS.items():
            cursor = db.execute(sql)
            with (destination / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow([column[0] for column in cursor.description])
                writer.writerows(cursor)


def build(root):
    output = root / "equipment.sqlite"
    descriptor, temporary_name = tempfile.mkstemp(prefix="equipment-", suffix=".building", dir=root)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with closing(sqlite3.connect(temporary)) as db:
            db.execute("PRAGMA cache_size=-16384")
            with db:
                counts = populate(db, root)
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("SQLite integrity check failed")
            db.execute("PRAGMA optimize")
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    export_csvs(output, root / "chart-data")
    return {"database": str(output), "bytes": output.stat().st_size, "classes": dict(counts)}


if __name__ == "__main__":
    print(json.dumps(build(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent), indent=2))
