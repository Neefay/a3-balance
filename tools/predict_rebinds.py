"""Predict which existing classes a config file would re-parent ("Updating base class" in the RPT).

Usage: python predict_rebinds.py <config.cpp> [...]   (uses validation/remaining/full/snapshot.sqlite)
Reads the file the way the engine does: each class's parent is looked up through the file's own
declarations (siblings, then the declared parents, then the root), and a forward declaration of a class
that is only inherited refers to the inherited class. Any existing class whose parent changes, in name
or in which class it points to, is reported. On the first pilot this reproduced the engine's log exactly.
"""
import json
from pathlib import Path
import re
import sys

from config_model import infer_bindings, load

TOKEN = re.compile(r'\s+|//[^\n]*|/\*.*?\*/|("(?:[^"]|"")*")|([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)(?![\w.])|(\[\])|([A-Za-z_]\w*)|(\+=|[{}\[\];:=,])', re.S)


def tokens(text):
    out, pos = [], 0
    while pos < len(text):
        m = TOKEN.match(text, pos)
        if not m:
            raise ValueError(f"Cannot read config near: {text[pos:pos + 40]!r}")
        pos = m.end()
        token = next((g for g in m.groups() if g is not None), None)
        if token is not None:
            out.append(token)
    return out


def declarations(text):
    """{node: (written parent, has body)} for every class under CfgWeapons/CfgVehicles/CfgAmmo."""
    toks, decls, i = tokens(text), {}, 0

    def block(scope):
        nonlocal i
        while i < len(toks) and toks[i] != "}":
            if toks[i] == "class":
                name, i, base = toks[i + 1], i + 2, ""
                if toks[i] == ":":
                    base, i = toks[i + 1], i + 2
                node = None if scope is None else (scope[0], name.lower(), ()) if len(scope) == 1 else scope[:2] + (scope[2] + (name.lower(),),)
                if toks[i] == "{":
                    i += 1
                    inner = (name,) if scope is None and name in ("CfgWeapons", "CfgVehicles", "CfgAmmo") else node
                    if node is not None:
                        decls[node] = (base, True)
                    block(inner if (scope is not None or inner is not None) else "skip")
                    i += 1
                    if i < len(toks) and toks[i] == ";":
                        i += 1
                else:
                    if node is not None:
                        decls.setdefault(node, (base, False))
                    i += 1
            else:
                depth = 0
                while True:
                    t = toks[i]
                    i += 1
                    depth += (t == "{") - (t == "}")
                    if t == ";" and depth <= 0:
                        break

    def top():
        nonlocal i
        while i < len(toks):
            if toks[i] == "class" and toks[i + 2] == "{":
                name, i = toks[i + 1], i + 3
                if name in ("CfgWeapons", "CfgVehicles", "CfgAmmo"):
                    block((name,))
                else:
                    depth = 1
                    while depth:
                        depth += (toks[i] == "{") - (toks[i] == "}")
                        i += 1
                    i -= 1
                i += 1
                if i < len(toks) and toks[i] == ";":
                    i += 1
            else:
                i += 1

    top()
    return decls


def container(node):
    return node[:2] + (node[2][:-1],)


def predict(model, text):
    decls = declarations(text)
    body = {n: b for n, (_, b) in decls.items()}

    def real(found):
        if found is not None and found[2] and not body.get(found) and found not in model.nodes:
            return model.member(container(found), found[2][-1])
        return found

    def in_file(node):
        name = decls[node][0].lower()
        if not name:
            return None
        if not node[2]:
            found = (node[0], name, ())
            return found if found in body else None
        scope = container(node)
        while True:
            sibling = scope[:2] + (scope[2] + (name,),)
            if sibling != node and sibling in body:
                return real(sibling)
            step = in_file(scope) if body.get(scope) else None
            while step is not None and body.get(step):
                child = step[:2] + (step[2] + (name,),)
                if child in body:
                    return real(child)
                step = in_file(step) if step in decls else None
            if not scope[2]:
                break
            scope = container(scope)
        found = (node[0], name, ())
        return found if found in body else None

    changes = []
    for node, (written, has_body) in decls.items():
        if not node[2] or not has_body or node not in model.nodes:
            continue   # top-level parents are checked by name below; new classes have no parent to change
        original = model.nodes[node]["base"]
        if written.lower() != original.lower() or (original and in_file(node) != model.bound.get(node)):
            changes.append({"class": node, "was": original, "now": written})
    for node, (written, has_body) in decls.items():
        if not node[2] and has_body and (node[0], node[1]) in model.parent:
            if written.lower() != model.parent[(node[0], node[1])].lower():
                changes.append({"class": node, "was": model.parent[(node[0], node[1])], "now": written})
    return changes


def bound_model(snapshot):
    model = load(snapshot)
    unexplained = infer_bindings(model)
    if unexplained:
        raise ValueError(f"The config model does not reproduce {len(unexplained)} captured values")
    for node in list(model.nodes):
        if node[2] and node not in model.bound:
            model.bound[node] = model.base(node)
    model.reset()
    return model


if __name__ == "__main__":
    sys.setrecursionlimit(20000)
    root = Path(__file__).resolve().parent
    model = bound_model(root / "validation/remaining/full/snapshot.sqlite")
    total = 0
    for path in sys.argv[1:]:
        changes = predict(model, Path(path).read_text(encoding="utf-8"))
        total += len(changes)
        print(f"{path}: {len(changes)} parent changes")
        for change in changes[:20]:
            print("   ", json.dumps(change))
    raise SystemExit(1 if total else 0)
