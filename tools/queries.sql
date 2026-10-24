-- Run individual statements against equipment.sqlite. Values describe the loaded snapshot.

-- One row per public helmet/head region; missing or text armor remains NULL.
SELECT classname, display_name, family, mass, armor, pass_through, value_status
FROM v_headgear_comparison
WHERE scope = 2
ORDER BY family, armor DESC, classname;

-- Chart-ready groups: cosmetic variants remain a count, not independent balance votes.
SELECT family, mass, armor, pass_through, count(*) AS class_count
FROM v_headgear_comparison
WHERE scope = 2 AND mass IS NOT NULL AND armor IS NOT NULL
GROUP BY family, mass, armor, pass_through
ORDER BY family, armor, mass;

-- Compare vest chest protection separately from abdomen/neck/other coverage.
SELECT classname, family, mass, maximum_load, armor, pass_through, value_status
FROM v_wearable_protection
WHERE kind = 'vest' AND scope = 2 AND lower(hitpoint) = 'hitchest'
ORDER BY armor DESC, classname;

-- Expressions can be reviewed without coercing them into zero-valued armor.
SELECT classname, kind, region, armor_raw_json, pass_through_raw_json
FROM v_wearable_protection
WHERE value_status = 'contains_text_expression'
ORDER BY classname, region;

-- Unresolved uniform links stay visible even though they have no armor rows.
SELECT classname, uniform_class, unit_link_status
FROM v_wearables
WHERE unit_link_status = 'unresolved'
ORDER BY classname;

-- Penetration multiplier is the engine's caliber; ACE diameter is a separate column.
SELECT classname, family, hit, penetration_multiplier, typical_speed,
       ace_caliber_mm, ace_bullet_mass_g, magazine_count
FROM v_bullets
WHERE classname LIKE '%556x45%'
ORDER BY classname;

-- Magazine muzzle speed and projectile damage-reference speed are separate values.
SELECT m.classname AS magazine, p.classname AS projectile, mag.rounds,
       mag.init_speed AS magazine_muzzle_speed, p.typical_speed AS damage_reference_speed
FROM magazines mag
JOIN configs m ON m.id = mag.class_id
JOIN v_ammunition p ON p.class_id = mag.projectile_class_id
WHERE p.classname = 'rhs_ammo_762x51_M80_Ball';

-- Actual draft deltas, without implying that the changes are installed.
SELECT classname, kind, field, old_number, proposed_number, delta, rule, confidence
FROM v_proposed_changes
ORDER BY kind, classname, field;

-- Work remaining by disposition.
SELECT c.status, cfg.section, count(*) AS class_count
FROM coverage c JOIN configs cfg ON cfg.id = c.class_id
GROUP BY c.status, cfg.section
ORDER BY c.status, cfg.section;

-- Anchor values remain region-specific.
SELECT * FROM v_anchor_regions ORDER BY kind, role, classname, region;

-- Source addons are many-to-many; family is only a convenient reference grouping.
SELECT addon FROM v_source_addons
WHERE section = 'CfgWeapons' AND classname = 'V_PlateCarrier1_rgr';

-- Ancestry depth 0 is the class itself, depth 1 its parent.
SELECT ancestor, depth FROM v_ancestry
WHERE section = 'CfgWeapons' AND classname = 'BRM_ACH_GREEN'
ORDER BY depth;

-- Original selected properties remain queryable as JSON for less common fields.
SELECT classname, json_extract(properties_json, '$.ACE_bulletMass') AS bullet_mass_g
FROM configs
WHERE section = 'CfgAmmo' AND classname = 'ACE_556x45_Ball_Mk262';

-- Dataset completeness and known gaps accompany the data.
SELECT json_extract(value_json, '$.status') AS status,
       json_extract(value_json, '$.missing_by_section') AS missing_by_section
FROM metadata WHERE key = 'extraction';

-- Vanilla five-cartridge targets; RHS columns are comparison observations only.
SELECT * FROM v_ammunition_family_scale ORDER BY cartridge;

-- Observed and proposed ammunition remain separate chart columns.
SELECT classname, cartridge, role, mapping_basis,
       hit, proposed_hit, penetration_multiplier, proposed_penetration_multiplier,
       typical_speed, proposed_typical_speed
FROM v_ammunition_mapping
WHERE proposed_hit IS NOT NULL
ORDER BY cartridge, classname;

-- Specialized cases still needing identity/model review in the five families.
SELECT classname, cartridge, mapping_status, reason
FROM v_ammunition_mapping
WHERE cartridge_code IN ('556x45','545x39','762x39','762x51','762x54')
  AND mapping_status LIKE 'review_%'
ORDER BY cartridge, classname;

-- These are observed values to retain if a changed ancestor is eventually patched.
SELECT * FROM v_ammunition_preservation_guards ORDER BY classname;

-- Vest classification and separate mass/capacity observations.
SELECT classname, display_name, role, assessment_status, mass, maximum_load,
       candidate_references_json, flags_json
FROM v_wearable_assessments WHERE kind='vest'
ORDER BY role, classname;

-- Uniform assessment: shared units and inheritance require review before overrides.
SELECT classname, uniform_class, assessment_status, shared_uniform_count,
       unit_descendant_count, declared_wearer_count, flags_json
FROM v_wearable_assessments WHERE kind='uniform'
ORDER BY assessment_status, classname;

-- Candidate comparisons are review evidence, not new patch targets.
SELECT * FROM v_wearable_reference_pairs
WHERE classname IN ('rhsusf_mbav_rifleman','rhsusf_iotv_ocp_Rifleman','U_simc_surf');

-- Raw expressions and missing values stay explicit in field comparisons.
SELECT classname, reference_class, path_json, current_present, reference_present,
       current_json, reference_json, current_number, reference_number
FROM v_wearable_comparisons
WHERE classname IN ('Belt_BLK','U_simc_surf','U_Simc_OG107_mk1_MC');

-- Potential unit override reach; ancestry is not property declaration ownership.
SELECT unit_class, resolved, uniform_count, descendant_count, declared_wearer_count
FROM v_uniform_unit_usage ORDER BY descendant_count DESC LIMIT 30;

-- Selected wearable tiers and the actual classes to patch (uniforms use CfgVehicles).
SELECT classname, kind, role, target_status, reference_class, patch_section,
       patch_class, field_changes, held_fields_json, notes_json
FROM v_wearable_targets WHERE field_changes > 0 ORDER BY kind, classname;

-- Missing preservation paths must be resolved before releasing inherited overrides.
SELECT * FROM v_wearable_preservation_guards
WHERE status = 'review_missing_descendant_path' ORDER BY section, classname;

-- Exact fields proposed for a given uniform's linked unit.
SELECT t.classname AS uniform, c.section, c.classname AS unit, c.path_json,
       c.old_json, c.proposed_json
FROM v_wearable_targets t JOIN v_proposed_changes c
  ON c.section=t.patch_section AND c.classname=t.patch_class
WHERE t.classname = 'U_simc_surf';

-- Prospective AP/subsonic checks retain observed specialized values.
SELECT * FROM v_ammunition_penetration_checks ORDER BY status, cartridge, classname;

-- Helmet-only pilot descendant requirements, separate from later vest/unit guards.
SELECT * FROM v_helmet_preservation_guards ORDER BY classname, path_json;
