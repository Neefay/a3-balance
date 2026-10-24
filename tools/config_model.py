"""A model of the loaded game config that knows where every value is defined, not just what it is.

The full-modset capture (import_remaining_capture.py) records, for each class and nested class, its parent
and the members it defines itself. From that the model rebuilds each class's own definitions and resolves
inheritance the way the engine does, so a patch can change a value where it is defined and the effect on
every class that inherits it can be computed before anything is built.
"""
from contextlib import closing
import json
import sqlite3

# Leaf fields the patch may change, plus scope (decides which classes matter).
LEAVES = ("armor", "passthrough", "explosionshielding", "hit", "caliber", "typicalspeed", "scope")
# Top-level members holding those leaves. VestItem and HeadgearItem keep HitpointsProtectionInfo at their top level.
ROOTS = {"CfgWeapons": ("iteminfo", "hitpointsprotectioninfo"), "CfgVehicles": ("hitpoints",), "CfgAmmo": None}


class Model:
    def __init__(self):
        self.name = {}      # (section, class lower) -> class name as written
        self.parent = {}    # (section, class lower) -> parent class name ("" for roots)
        self.sources = {}   # (section, class lower) -> configSourceAddonList
        self.nodes = {}     # node -> {"base": name, "members": {lower: name}} for every locally defined class node
        self.values = {}    # (node, leaf lower) -> (name as written, value) for every locally defined leaf
        self.observed = {}  # (section, class lower, path lower) -> captured effective value of a leaf
        self.bound = {}     # node -> node: parents the engine bound elsewhere than the nearest same-named class
        self.parent_names = {}  # class lower -> name as written, for ancestors outside the captured sections
        self.uniform_units = set()  # unit classes some uniform links to
        self._memo = {}

    # A node is (section, owner class lower, nested path lower); a top-level class is (section, class, ()).
    @staticmethod
    def top(section, name):
        return (section, name.lower(), ())

    def members(self, node):
        return self.nodes[node]["members"] if node in self.nodes else {}

    def base(self, node):
        """The node this node inherits from, resolved like the engine: inside the container's parent, then outward."""
        if node in self.bound:
            return self.bound[node]
        key = ("base", node)
        if key in self._memo:
            return self._memo[key]
        section, owner, path = node
        result = None
        if not path:
            parent = self.parent.get((section, owner), "")
            result = self.top(section, parent) if parent and (section, parent.lower()) in self.parent else None
        else:
            name = self.nodes[node]["base"]
            if name:
                container = (section, owner, path[:-1])
                scope, lower = container, name.lower()
                while result is None:
                    # A sibling of the same scope first (HitLeftArm: HitHands), then what the scope inherits.
                    sibling = scope[:2] + (scope[2] + (lower,),)
                    if sibling != node and lower in self.members(scope) and sibling in self.nodes:
                        result = sibling
                        break
                    inherited = self.base(scope) if scope in self.nodes else None
                    result = self.member(inherited, lower) if inherited else None
                    if result is None:
                        if not scope[2]:
                            top = self.top(section, name)
                            result = top if (section, name.lower()) in self.parent else None
                            break
                        scope = (section, scope[1], scope[2][:-1])
        self._memo[key] = result
        return result

    def member(self, node, name):
        """The class node named `name` as seen from `node`: its own, or inherited."""
        key = ("member", node, name)
        if key in self._memo:
            return self._memo[key]
        result = None
        if name in self.members(node) and node[:2] + (node[2] + (name,),) in self.nodes:
            result = node[:2] + (node[2] + (name,),)
        else:
            base = self.base(node)
            result = self.member(base, name) if base else None
        self._memo[key] = result
        return result

    def owner(self, node, leaf):
        """The node that defines `leaf` as seen from `node`."""
        key = ("owner", node, leaf)
        if key in self._memo:
            return self._memo[key]
        result = node if (node, leaf) in self.values else None
        if result is None:
            base = self.base(node)
            result = self.owner(base, leaf) if base else None
        self._memo[key] = result
        return result

    def resolve(self, section, classname, path):
        """(node, leaf) defining the effective value of class `classname` at `path`, or None."""
        node = self.top(section, classname)
        for part in path[:-1]:
            node = self.member(node, part.lower())
            if node is None:
                return None
        owner = self.owner(node, path[-1].lower())
        return (owner, path[-1].lower()) if owner else None

    def value(self, section, classname, path):
        found = self.resolve(section, classname, path)
        return self.values[found][1] if found else None

    def reset(self):
        self._memo.clear()


def load(snapshot):
    """Build the model from a full-modset snapshot.sqlite."""
    model = Model()
    leaf_sql = ",".join(f"'{leaf}'" for leaf in LEAVES)
    with closing(sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)) as db:
        for section, name, addons, ancestry, direct in db.execute(
                "SELECT section, classname, source_addons, ancestry, direct_names FROM configs WHERE section IN ('CfgWeapons','CfgVehicles','CfgAmmo')"):
            key = (section, name.lower())
            chain = json.loads(ancestry)
            model.name[key] = name
            model.parent[key] = chain[1] if len(chain) > 1 else ""
            for ancestor in chain[1:]:
                model.parent_names.setdefault(ancestor.lower(), ancestor)
            model.sources[key] = json.loads(addons)
            model.nodes[(section, name.lower(), ())] = {"base": model.parent[key],
                                                       "members": {n.lower(): n for n in json.loads(direct)}}
        # Units a uniform puts its wearer in: their values matter even when hidden.
        model.uniform_units = {json.loads(v).lower() for (v,) in db.execute(
            "SELECT value FROM fields WHERE section='CfgWeapons' AND lower(path)='[\"iteminfo\",\"uniformclass\"]' AND kind='text'")}
        rows = db.execute(f"""SELECT section, classname, path, kind, value FROM fields
            WHERE section IN ('CfgWeapons','CfgVehicles','CfgAmmo')
              AND (kind = 'class' OR lower(json_extract(path, '$[#-1]')) IN ({leaf_sql}))
            ORDER BY section, classname, length(path)""")
        for section, name, path, kind, value in rows:
            parts = json.loads(path)
            lower = tuple(p.lower() for p in parts)
            root = ROOTS[section]
            if root and lower[0] not in root and lower != ("scope",):
                continue
            cls = name.lower()
            container = (section, cls, lower[:-1])
            # Local only if every step is defined by this class itself.
            local = container in model.nodes and lower[-1] in model.nodes[container]["members"]
            data = json.loads(value)
            if kind == "class":
                if local:
                    model.nodes[(section, cls, lower)] = {"base": data["parent"],
                                                         "members": {n.lower(): n for n in data["direct_names"]}}
            elif kind == "number" or kind == "text":
                model.observed[(section, cls, lower)] = data
                if local:
                    model.values[(container, lower[-1])] = (parts[-1], data)
    return model


def check(model, keys=None):
    """Every captured effective value must be what the model's inheritance resolution gives."""
    bad = []
    for key in keys if keys is not None else model.observed:
        section, cls, path = key
        value = model.observed[key]
        got = model.value(section, model.name[(section, cls)], path)
        if got != value:
            bad.append({"section": section, "classname": model.name[(section, cls)], "path": list(path), "observed": value, "model": got})
    return bad


def candidates(model, node):
    """Every class node the engine could bind this node's parent name to, nearest first."""
    section, owner, path = node
    name = model.nodes[node]["base"].lower()
    found, scope = [], (section, owner, path[:-1])
    while True:
        sibling = scope[:2] + (scope[2] + (name,),)
        if sibling != node and name in model.members(scope) and sibling in model.nodes:
            found.append(sibling)
        ancestor = model.base(scope) if scope in model.nodes else None
        while ancestor is not None:
            child = ancestor[:2] + (ancestor[2] + (name,),)
            if name in model.members(ancestor) and child in model.nodes and child not in found:
                found.append(child)
            ancestor = model.base(ancestor)
        if not scope[2]:
            break
        scope = (section, scope[1], scope[2][:-1])
    root = model.top(section, name)
    if (section, name) in model.parent and root not in found:
        found.append(root)
    return found


def infer_bindings(model):
    """Rebind the parents that only an alternative same-named class explains; returns what stays unexplained."""
    by_class = {}
    for key in model.observed:
        by_class.setdefault(key[:2], []).append(key)
    bad = check(model)
    for _ in range(4):
        if not bad:
            break
        suspects = []
        for row in bad:
            section, cls = row["section"], row["classname"].lower()
            # the deepest node of this class along the failing path, i.e. where resolution leaves the class
            path = tuple(row["path"][:-1])
            for depth in range(len(path), 0, -1):
                node = (section, cls, path[:depth])
                if node in model.nodes and model.nodes[node]["base"]:
                    suspects.append(node)
                    break
        for node in dict.fromkeys(sorted(suspects, key=lambda n: len(n[2]))):
            keys = [k for k in by_class[node[:2]] if k[2][:len(node[2])] == node[2]]
            for target in candidates(model, node):
                model.bound[node] = target
                model.reset()
                if not check(model, keys):
                    break
            else:
                del model.bound[node]
                model.reset()
        bad = check(model)
    return bad
