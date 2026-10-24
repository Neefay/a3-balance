"""Model, planner and emitter tests on a small synthetic modset.

The captured (effective) values are produced by an independent mini-engine that follows explicitly stated
parent bindings, so the model's own name resolution and binding inference are what is tested.
"""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

from build_patch import partition
from config_model import check, infer_bindings, load
from emit_patch import PatchFile
from import_remaining_capture import schema
from plan_patch import plan

sys.setrecursionlimit(10000)

# class -> (section, parent, sources, scope, local tree). A local class node is
# {"base": name, "bound": (class, path) or None, "members": {...}}; leaves are numbers.
def node(base="", bound=None, **members):
    return {"base": base, "bound": bound, "members": members}


MODSET = {
    # vanilla
    "VestItem": ("CfgWeapons", "", ["A3_Characters_F"], 0, {"HitpointsProtectionInfo": node(Chest=node(armor=0, passThrough=1))}),
    "ItemCore": ("CfgWeapons", "", ["A3_Weapons_F"], 0, {}),
    "Vest_Camo_Base": ("CfgWeapons", "ItemCore", ["A3_Characters_F"], 0, {"ItemInfo": node("VestItem", ("VestItem", ()))}),
    # a mod: hidden base that owns the protection, three public vests
    "ModBase": ("CfgWeapons", "Vest_Camo_Base", ["mod_gear"], 0, {"ItemInfo": node("ItemInfo", ("Vest_Camo_Base", ("ItemInfo",)),
                HitpointsProtectionInfo=node(Chest=node(armor=22, passThrough=0.3)))}),
    "ModA": ("CfgWeapons", "ModBase", ["mod_gear"], 2, {}),
    "ModB": ("CfgWeapons", "ModBase", ["mod_gear"], 2, {"ItemInfo": node("ItemInfo", ("ModBase", ("ItemInfo",)))}),
    "ModC": ("CfgWeapons", "ModBase", ["mod_gear"], 2, {}),
    # a public base that is not a target; a child that is (needs a created ItemInfo); a grandchild bound past it
    "Plain": ("CfgWeapons", "Vest_Camo_Base", ["mod_gear"], 2, {"ItemInfo": node("ItemInfo", ("Vest_Camo_Base", ("ItemInfo",)),
              HitpointsProtectionInfo=node(Chest=node(armor=12, passThrough=0.4)))}),
    "Mid": ("CfgWeapons", "Plain", ["mod_gear"], 2, {}),
    "Leaf": ("CfgWeapons", "Mid", ["mod_gear"], 2, {"ItemInfo": node("ItemInfo", ("Plain", ("ItemInfo",)),
             HitpointsProtectionInfo=node(Chest=node(armor=30)))}),
    # units: a sibling parent, and a mod unit whose HitPoints the engine bound past its own parent
    "CAManBase": ("CfgVehicles", "", ["A3_Characters_F"], 0, {"HitPoints": node(HitHands=node(armor=3), HitLeftArm=node("HitHands", ("CAManBase", ("HitPoints", "HitHands"))))}),
    "O_Base": ("CfgVehicles", "CAManBase", ["A3_Characters_F"], 1, {"HitPoints": node(HitHands=node(armor=6), HitLeftArm=node("HitHands", ("O_Base", ("HitPoints", "HitHands"))))}),
    "SnsBase": ("CfgVehicles", "O_Base", ["simc_core"], 1, {"HitPoints": node("HitPoints", ("CAManBase", ("HitPoints",)), HitHands=node(armor=5))}),
    "SnsUnit": ("CfgVehicles", "SnsBase", ["simc_core"], 1, {}),
}
UNIFORMS = {"U_Sns": "SnsUnit"}


def local(cls, path=()):
    tree = {"base": MODSET[cls][1], "bound": None, "members": MODSET[cls][4]} if not path else None
    if path:
        tree = local(cls)
        for part in path:
            tree = tree["members"].get(part) if tree else None
    return tree


def effective(cls, path=()):
    """{member: value or ('class', defining class, defining path)} for class cls at nested path."""
    if not path:
        own = MODSET[cls][4]
        out = effective(MODSET[cls][1]) if MODSET[cls][1] else {}
        out = dict(out)
        for name, value in own.items():
            out[name] = ("class", cls, (name,)) if isinstance(value, dict) else value
        return out
    defining = defining_node(cls, path)
    return None if defining is None else members_of(*defining)


def members_of(owner, opath):
    """Members of the class node defined at (owner, opath): its own, then its bound parent's."""
    if not opath:
        return effective(owner)
    here = local(owner, opath)
    out = dict(members_of(*here["bound"]) if here["bound"] else {})
    for name, value in here["members"].items():
        out[name] = ("class", owner, opath + (name,)) if isinstance(value, dict) else value
    return out


def defining_node(cls, path):
    current, entry = effective(cls), None
    for part in path:
        entry = current.get(part) if current else None
        if not isinstance(entry, tuple):
            return None
        current = members_of(entry[1], entry[2])
    return entry[1], entry[2]


def rows(cls, path=()):
    """Captured field rows for class cls, as the batch capture writes them."""
    out = []
    for name, value in (effective(cls, path) or {}).items():
        full = path + (name,)
        if isinstance(value, tuple):
            here = local(value[1], value[2])
            out.append((json.dumps(list(full)), "class", json.dumps({"parent": here["base"], "direct_names": list(here["members"])})))
            out += rows(cls, full)
        else:
            out.append((json.dumps(list(full)), "number", json.dumps(value)))
    return out


def snapshot(folder):
    path = folder / "snapshot.sqlite"
    with closing(sqlite3.connect(path)) as db:
        schema(db)
        for cls, (section, parent, sources, scope, tree) in MODSET.items():
            ancestry, p = [cls], parent
            while p:
                ancestry.append(p)
                p = MODSET[p][1]
            db.execute("INSERT INTO configs VALUES(?,?,?,?,?)", (section, cls, json.dumps(sources), json.dumps(ancestry), json.dumps(list(tree) + ["scope"])))
            db.execute("INSERT INTO fields VALUES(?,?,?,?,?)", (section, cls, '["scope"]', "number", json.dumps(scope)))
            for row in rows(cls):
                db.execute("INSERT INTO fields VALUES(?,?,?,?,?)", (section, cls) + row)
        for uniform, unit in UNIFORMS.items():
            db.execute("INSERT INTO configs VALUES(?,?,?,?,?)", ("CfgWeapons", uniform, '["simc_core"]', json.dumps([uniform]), '["ItemInfo"]'))
            db.execute("INSERT INTO fields VALUES(?,?,?,?,?)", ("CfgWeapons", uniform, '["ItemInfo","uniformClass"]', "text", json.dumps(unit)))
        db.commit()
    return path


CHEST = ("iteminfo", "hitpointsprotectioninfo", "chest", "armor")
NAMES = {CHEST: ("ItemInfo", "HitpointsProtectionInfo", "Chest", "armor"), ("hitpoints", "hithands", "armor"): ("HitPoints", "HitHands", "armor")}


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.model = load(snapshot(Path(self.temp.name)))

    def tearDown(self):
        self.temp.cleanup()

    def test_model_reproduces_the_capture_and_infers_the_skipped_parent(self):
        bad = check(self.model)
        self.assertTrue(bad)  # SnsUnit's HitLeftArm is 3, not O_Base's 6: the naive lookup is wrong
        self.assertEqual(infer_bindings(self.model), [])
        self.assertEqual(self.model.bound[("CfgVehicles", "snsbase", ("hitpoints",))], ("CfgVehicles", "camanbase", ("hitpoints",)))
        self.assertEqual(self.model.value("CfgVehicles", "SnsUnit", ("hitpoints", "hitleftarm", "armor")), 3)
        self.assertEqual(self.model.value("CfgVehicles", "O_Base", ("hitpoints", "hitleftarm", "armor")), 6)

    def plan(self, edits):
        self.assertEqual(infer_bindings(self.model), [])
        return plan(self.model, edits, NAMES)

    def test_plan_reaches_every_target_and_keeps_everything_else(self):
        edits = {("CfgWeapons", "moda", CHEST): 20, ("CfgWeapons", "modb", CHEST): 20, ("CfgWeapons", "mid", CHEST): 8,
                 ("CfgVehicles", "snsunit", ("hitpoints", "hithands", "armor")): 3}
        placements, report = self.plan(edits)
        value = lambda s, c, p: self.model.value(s, c, p)
        self.assertEqual([value("CfgWeapons", c, CHEST) for c in ("ModA", "ModB", "ModC", "Mid", "Plain", "Leaf")], [20, 20, 22, 8, 12, 30])
        self.assertEqual(value("CfgVehicles", "SnsUnit", ("hitpoints", "hithands", "armor")), 3)
        self.assertEqual(value("CfgVehicles", "SnsUnit", ("hitpoints", "hitleftarm", "armor")), 3)
        self.assertEqual(value("CfgVehicles", "O_Base", ("hitpoints", "hithands", "armor")), 6)
        # The hidden base takes the new value once; only the non-target keeps the old one with its own write.
        self.assertEqual(placements[("CfgWeapons", "modbase", CHEST)], 20)
        self.assertEqual(placements[("CfgWeapons", "modc", CHEST)], 22)
        self.assertEqual(report["writes"], 4)
        self.assertFalse(any(cls in ("vestitem", "vest_camo_base", "camanbase", "o_base") for _, cls, _ in placements))

    def test_files_restate_parents_and_split_when_a_binding_would_move(self):
        edits = {("CfgWeapons", "mid", CHEST): 8, ("CfgWeapons", "leaf", CHEST): 24}
        placements, _ = self.plan(edits)
        writes = [(cls, path, value) for (section, cls, path), value in placements.items() if section == "CfgWeapons"]
        files = partition(self.model, "CfgWeapons", writes)
        # Mid gets a new ItemInfo; in the same file Leaf's ItemInfo would bind to it instead of Plain's.
        self.assertEqual(len(files), 2)
        for f in files:
            self.assertEqual(f.verify(), [])
        text = "\n".join(line for f in files for line in f.render())
        self.assertIn("class Mid: Plain", text)
        self.assertIn("class ItemInfo: ItemInfo", text)
        self.assertIn("class Leaf: Mid", text)
        self.assertNotRegex(text, r"class \w+: \w+;")  # forward declarations never name a parent

    def test_a_conflicting_file_is_caught(self):
        edits = {("CfgWeapons", "mid", CHEST): 8, ("CfgWeapons", "leaf", CHEST): 24}
        placements, _ = self.plan(edits)
        f = PatchFile(self.model, "CfgWeapons")
        for (section, cls, path), value in placements.items():
            node = self.model.top(section, cls)
            for part in path[:-1]:
                node = node[:2] + (node[2] + (part,),)
            f.set(node, path[-1], "armor", value)
        f.close()
        problems = f.verify()
        self.assertTrue(problems)
        self.assertEqual(problems[0]["node"][1], "leaf")


if __name__ == "__main__":
    unittest.main()
