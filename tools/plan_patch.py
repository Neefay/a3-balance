"""Plan the smallest patch that gives every class its target value and leaves every other value alone.

Each changed value is grouped with every class that inherits it from the same definition. Within a group a
small tree search picks where to write: at the definition when its inheritors agree, on individual classes
only where they must differ. Hidden (scope 0) classes that aren't targets may take any value, so one write on
a shared base can cover its public children. Vanilla classes are never written.

The engine binds a nested class's parent when the file declaring it loads; later files can add members to
that parent but don't rebind it. So existing bindings are frozen before the patch is applied, the patch is
simulated on the model, and any class left with the wrong value gets its own write until none is.
"""
from collections import defaultdict

VANILLA = ("a3_", "a3data", "core")


def vanilla(model, section, cls):
    sources = model.sources.get((section, cls), [])
    return not sources or all(s.lower().startswith(VANILLA) for s in sources)


def free(model, section, cls):
    """Classes no player or mission can meet on their own, which may follow their children's new values:
    private (scope 0) classes, and hidden (scope 1) ones except units a uniform puts its wearer in.
    Rounds are always kept: magazines can load any of them."""
    if section == "CfgAmmo":
        return False
    scope = model.observed.get((section, cls, ("scope",)))
    if scope == 0:
        return True
    return scope == 1 and not (section == "CfgVehicles" and cls in model.uniform_units)


def freeze(model):
    for node in model.nodes:
        if node[2] and node not in model.bound:
            model.bound[node] = model.base(node)
    model.reset()


def write(model, section, cls, path, names, value):
    """Set `value` at class `cls`, creating the nested classes it lacks as `class X: X`. Returns created nodes."""
    created, node = [], model.top(section, cls)
    for part, name in zip(path[:-1], names[:-1]):
        child = node[:2] + (node[2] + (part,),)
        if not (part in model.members(node) and child in model.nodes):
            target = model.member(node, part)
            model.nodes[child] = {"base": name, "members": {}, "created": True}
            model.nodes[node]["members"][part] = name
            model.bound[child] = target
            created.append(child)
        node = child
    model.values[(node, path[-1])] = (names[-1], value)
    model.nodes[node]["members"][path[-1]] = names[-1]
    model.reset()
    return created


def plan(model, edits, names):
    """edits: {(section, class lower, path lower): proposed}; names: path lower -> path as written.
    Returns (placements {(section, class, path): value}, report)."""
    inferred = set(model.bound)
    freeze(model)
    paths = defaultdict(set)
    for section, _, path in edits:
        paths[section].add(path)
    groups = defaultdict(dict)
    for (section, cls, path) in model.observed:
        if path in paths[section]:
            owner = model.resolve(section, model.name[(section, cls)], path)
            if owner is not None:
                groups[(section, owner)][cls] = path

    def want(section, cls, path):
        if (section, cls, path) in edits:
            return edits[(section, cls, path)]
        if free(model, section, cls):
            return None
        return model.observed[(section, cls, path)]

    affected = [g for g in groups if any((g[0], c, p) in edits for c, p in groups[g].items())]
    placements = {}
    for section, (owner_node, leaf) in affected:
        members = groups[(section, (owner_node, leaf))]
        desired = {c: want(section, c, p) for c, p in members.items()}
        original = model.values[(owner_node, leaf)][1]
        # Tree: a member's parent is the nearest other member its lookup passes through.
        parent = {}
        for cls, path in members.items():
            up, node = None, model.top(section, cls)
            for part in path[:-1]:
                node = model.member(node, part)
            while node is not None:
                if node[1] != cls and node[1] in members:
                    up = node[1]
                    break
                if (node, leaf) in model.values:
                    break
                node = model.base(node)
            parent[cls] = up
        children = defaultdict(list)
        for cls, up in parent.items():
            children[up].append(cls)
        values = {original} | {v for v in desired.values() if v is not None}
        memo = {}

        def created(cls):
            """Nested classes a write on cls would have to create (fewer is better on a tie)."""
            node, count = model.top(section, cls), 0
            for part in members[cls][:-1]:
                node = node[:2] + (node[2] + (part,),)
                count += node not in model.nodes
            return count

        def add(a, b):
            return (a[0] + b[0], a[1] + b[1])

        def cost(cls, incoming):
            """((writes, created classes), value written at cls or None) for the subtree under cls."""
            if (cls, incoming) not in memo:
                memo[(cls, incoming)] = ((float("inf"), 0), None)
                best = ((float("inf"), 0), None)
                if desired[cls] is None or desired[cls] == incoming:
                    total = (0, 0)
                    for c in children[cls]:
                        total = add(total, cost(c, incoming)[0])
                    best = (total, None)
                if not vanilla(model, section, cls):
                    for v in values:
                        if v != incoming and desired[cls] in (None, v):
                            total = (1, created(cls))
                            for c in children[cls]:
                                total = add(total, cost(c, v)[0])
                            if total < best[0]:
                                best = (total, v)
                memo[(cls, incoming)] = best
            return memo[(cls, incoming)]

        def place(cls, incoming):
            choice = cost(cls, incoming)[1]
            if choice is not None:
                placements[(section, cls, members[cls])] = choice
            for c in children[cls]:
                place(c, incoming if choice is None else choice)

        for root in children[None]:
            place(root, original)

    # Apply, simulate, and give any class that still disagrees its own write.
    created = []
    for (section, cls, path), value in sorted(placements.items(), key=lambda kv: len(kv[0][2])):
        created += write(model, section, cls, path, names[path], value)
    rounds = 0
    while True:
        wrong = []
        for (section, cls, path), observed in model.observed.items():
            if path not in paths[section]:
                continue
            target = want(section, cls, path)
            if target is not None and model.value(section, model.name[(section, cls)], path) != target:
                wrong.append((section, cls, path, target))
        if not wrong or rounds > 8:
            break
        rounds += 1
        for section, cls, path, target in wrong:
            if vanilla(model, section, cls):
                raise ValueError(f"A vanilla class would change: {section} {cls} {path}")
            placements[(section, cls, path)] = target
            created += write(model, section, cls, path, names[path], target)
    if wrong:
        raise ValueError(f"{len(wrong)} values could not be placed, e.g. {wrong[:3]}")
    live = check_live(model, inferred, created, paths, want)
    if live:
        raise ValueError(f"{len(live)} values would be wrong if the engine re-resolved parents at load, e.g. {live[:3]}")
    return placements, {"groups": len(affected), "writes": len(placements), "created_classes": len(created),
                        "fix_rounds": rounds}


def check_live(model, inferred, created, paths, want):
    """The plan must also hold if the engine re-resolved every parent by name after the patch loads,
    keeping only the bindings the capture proves (and the patch's own new classes)."""
    frozen = dict(model.bound)
    model.bound = {n: t for n, t in frozen.items() if n in inferred or n in set(created)}
    model.reset()
    try:
        return [(s, c, p) for (s, c, p) in model.observed if p in paths[s]
                and want(s, c, p) is not None and model.value(s, model.name[(s, c)], p) != want(s, c, p)]
    finally:
        model.bound = frozen
        model.reset()
