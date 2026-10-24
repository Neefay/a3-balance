import unittest

from import_pilot_session import compare, summarize, summarize_blast, validate


def manifest():
    return {"suite_id": "suite", "max_shots": 12, "trials": 2, "expected_results": 8, "expected_blast_results": 2, "blast_distance": 4,
            "rounds": [{"cartridge": "5.56x45", "classname": "B_Ball", "role": "reference", "ladder_role": "ball_named"},
                       {"cartridge": "5.56x45", "classname": "rhs_Ball", "role": "patched", "ladder_role": "ball_named", "compare_with": "B_Ball"},
                       {"cartridge": "5.56x45", "classname": "rhs_AP", "role": "special", "ladder_role": "armor_piercing_named", "compare_with": "B_Ball"}],
            "targets": {"chest": [{"classname": "V_Plate", "role": "reference", "tier": "plate", "armor": 20, "passThrough": .2},
                                  {"classname": "rhs_vest", "role": "patched", "tier": "plate", "armor": 20, "passThrough": .2, "compare_with": "V_Plate"}],
                        "head": []}}


def shot(ammo, gear, shots):
    return ["RESULT", ammo, "chest", gear, 1, shots, "unconscious" if shots > 0 else "standing", 0.1, [9, 0.87, 920], gear]


class SessionTests(unittest.TestCase):
    def test_patched_round_and_item_match_their_references(self):
        results = [shot("B_Ball", "V_Plate", 9), shot("B_Ball", "V_Plate", 9), shot("rhs_Ball", "V_Plate", 9), shot("rhs_Ball", "V_Plate", 10),
                   shot("rhs_Ball", "rhs_vest", 10), shot("rhs_Ball", "rhs_vest", 9), shot("rhs_AP", "V_Plate", 4), shot("rhs_AP", "V_Plate", 5)]
        results += [["BLAST", "", 1, "standing", 0.5, [], 0.1, "U_B"], ["BLAST", "U_mod", 1, "standing", 0.55, [], 0.1, "U_mod"]]
        records = [["BEGIN_ACCEPT", 1, "suite", 4, 2, 2, 1, [], [], [], [], True, "build"]] + results + [["END_ACCEPT", 1, "suite", len(results) + 2, len(results)]]
        begin, parsed = validate(records, manifest())
        checks, order, blasts, held = compare(summarize(parsed, manifest()), summarize_blast(parsed), manifest())
        self.assertEqual([(c["kind"], c["verdict"]) for c in checks], [("round", "match"), ("item", "match")])
        self.assertEqual(order[0]["verdict"], "in order")
        self.assertEqual(blasts[0]["verdict"], "similar")

    def test_held_items_are_reported_apart_from_the_pass_checks(self):
        m = manifest()
        m["targets"]["uniform"] = [{"classname": "U_Polo", "role": "reference", "tier": "civilian"},
                                   {"classname": "U_civ", "role": "held", "tier": "civilian", "compare_with": "U_Polo"}]
        uniform = lambda gear, shots: ["RESULT", "rhs_Ball", "uniform", gear, 1, shots, "unconscious", 0.1, [9, 0.87, 920], gear]
        checks, _, _, held = compare(summarize([uniform("U_Polo", 1), uniform("U_civ", 4)], m), [], m)
        self.assertEqual(checks, [])
        self.assertEqual([(h["subject"], h["verdict"]) for h in held], [("U_civ", "differs")])

    def test_mismatch_survivors_and_counts(self):
        results = [shot("B_Ball", "V_Plate", 3), shot("B_Ball", "V_Plate", 3), shot("rhs_Ball", "V_Plate", -1), shot("rhs_Ball", "V_Plate", -1),
                   shot("rhs_Ball", "rhs_vest", -1), shot("rhs_Ball", "rhs_vest", -1), shot("rhs_AP", "V_Plate", 6), shot("rhs_AP", "V_Plate", 6)]
        checks, order, _, _ = compare(summarize(results, manifest()), [], manifest())
        self.assertEqual([c["verdict"] for c in checks], ["differs", "match"])
        self.assertEqual(order[0]["verdict"], "needs more shots than ball")
        records = [["BEGIN_ACCEPT", 1, "suite", 4, 2, 2, 1, [], [], [], [], True, "build"]] + results + [["END_ACCEPT", 1, "suite", len(results) + 2, len(results)]]
        with self.assertRaises(ValueError):
            validate(records, manifest())


if __name__ == "__main__":
    unittest.main()
