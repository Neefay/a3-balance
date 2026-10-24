"""Write a plan as config patches: self-contained files that declare only what their values need.

Every class is reopened with the parent it already has; nested classes the patch creates inherit the class
they stand in for (`class Chest: Chest`). The engine finds a parent named inside a file through that file's
own declarations, so each file declares the classes leading to every parent it names, and a simulation of
that in-file lookup must find exactly the parent the model says the engine bound. A file that would bind
anything differently is refused.
"""
from build_helmet_pilot import literal


def container(node):
    return node[:2] + (node[2][:-1],)


class PatchFile:
    def __init__(self, model, section):
        self.model, self.section = model, section
        self.body = {}      # node -> True (declared with a body) / False (forward declaration)
        self.values = {}    # node -> {leaf lower: (name, value)}

    # -- declaring ---------------------------------------------------------------------------------
    def open(self, node):
        for depth in range(len(node[2]) + 1):
            self.body[node[:2] + (node[2][:depth],)] = True

    def forward(self, node):
        if node[2]:
            self.open(container(node))
        self.body.setdefault(node, False)

    def set(self, node, leaf, name, value):
        self.open(node)
        self.values.setdefault(node, {})[leaf] = (name, value)

    # -- the model's view ----------------------------------------------------------------------------
    def target(self, node):
        """The node the engine binds this node's parent to."""
        if not node[2]:
            parent = self.model.parent[(self.section, node[1])]
            return self.model.top(self.section, parent) if parent else None
        if not self.model.nodes[node]["base"]:
            return None
        return self.model.bound.get(node) or self.model.base(node)

    def name(self, node):
        if not node[2]:
            key = (self.section, node[1])
            return self.model.name[key] if key in self.model.name else self.model.parent_names[node[1]]
        return self.model.members(container(node))[node[2][-1]]

    def base_name(self, node):
        return self.model.parent[(self.section, node[1])] if not node[2] else self.model.nodes[node]["base"]

    # -- closing over parents --------------------------------------------------------------------------
    def lead(self, node, target):
        """Declare the in-file path from node to its bound parent."""
        if not node[2] or container(target) == container(node) or not target[2]:
            self.forward(target)          # top-level parent, sibling, or a root class such as VestItem
            return
        scope = container(node)
        while True:
            step = self.target(scope)
            while step is not None:
                if step == container(target):
                    self.open(step)
                    self.forward(target)
                    return
                self.open(step)
                step = self.target(step)
            if not scope[2]:
                raise ValueError(f"No in-file path from {node} to {target}")
            scope = container(scope)

    def close(self):
        done = set()
        while True:
            todo = [n for n, b in self.body.items() if b and n not in done]
            if not todo:
                return
            for node in todo:
                done.add(node)
                target = self.target(node)
                if target is not None:
                    self.lead(node, target)

    # -- the file's own view -------------------------------------------------------------------------
    def in_file(self, node):
        """Resolve node's parent from this file's declarations alone, like the engine does."""
        name = self.base_name(node).lower()
        if not name:
            return None
        if not node[2]:
            found = self.model.top(self.section, name)
            return found if found in self.body else None
        scope = container(node)
        while True:
            sibling = scope[:2] + (scope[2] + (name,),)
            if sibling != node and sibling in self.body:
                return sibling
            step = self.in_file(scope) if self.body.get(scope) else None
            while step is not None and self.body.get(step):
                child = step[:2] + (step[2] + (name,),)
                if child in self.body:
                    return child
                step = self.in_file(step)
            if not scope[2]:
                break
            scope = container(scope)
        root = self.model.top(self.section, name)
        return root if root in self.body else None

    def verify(self):
        problems = []
        for node, body in self.body.items():
            # A forward declaration of a class that is only inherited would refer to the inherited one;
            # this file only ever names classes where they are defined.
            if node[2] and node not in self.model.nodes:
                problems.append({"node": node, "bound": None, "in_file": None, "reason": "declares a class that is not defined there"})
                continue
            if body and self.base_name(node):
                expected, got = self.target(node), self.in_file(node)
                if got != expected:
                    problems.append({"node": node, "bound": expected, "in_file": got})
        return problems

    # -- writing --------------------------------------------------------------------------------------
    def render(self):
        kids = {}
        for node in self.body:
            if node[2]:
                kids.setdefault(container(node), []).append(node)
        tops = [n for n in self.body if not n[2]]
        lines = [f"class {self.section}", "{"]

        def ordered(nodes):
            nodes = sorted(nodes, key=lambda n: (self.body[n], self.name(n).lower()))
            out, placed = [], set()
            while nodes:
                for n in nodes:
                    dep = self.in_file(n) if self.body[n] else None
                    if dep is None or dep not in nodes or dep in placed or dep == n:
                        out.append(n)
                        placed.add(n)
                        nodes.remove(n)
                        break
                else:
                    raise ValueError("Circular declarations")
            return out

        def emit(node, indent):
            pad = "    " * indent
            if not self.body[node]:
                lines.append(f"{pad}class {self.name(node)};")
                return
            base = self.base_name(node)
            head = f"class {self.name(node)}" + (f": {base}" if base else "")
            values = self.values.get(node, {})
            children = kids.get(node, [])
            if not values and not children:
                lines.append(f"{pad}{head} {{}};")
                return
            lines.extend([pad + head, pad + "{"])
            for name, value in values.values():
                lines.append(f"{pad}    {name} = {literal(value)};")
            for child in ordered(children):
                emit(child, indent + 1)
            lines.append(pad + "};")

        for node in ordered(tops):
            emit(node, 1)
        lines.append("};")
        return lines

    def classes(self):
        """Top-level classes declared with a body (for load order)."""
        return [n[1] for n, b in self.body.items() if b and not n[2]]
