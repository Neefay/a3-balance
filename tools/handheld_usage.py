"""Classify projectile use from a full-preset capture snapshot (validation/remaining).

A projectile is handheld_only when every magazine that loads it is fed only to
primary/handgun weapons (CfgWeapons type 1 or 2), no such weapon is mounted on a
non-man vehicle, the magazine itself is not listed by a non-man vehicle or turret,
and it carries no pylon metadata. Man-class loadouts are infantry use, not
vehicle use. Config associations cannot exclude script-added loadouts.
"""
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys

HANDHELD_TYPES = {"1", "2"}


def classify(snapshot, projectiles):
    db = sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True)
    men = {name.lower() for (name,) in db.execute(
        "SELECT classname FROM configs WHERE section='CfgVehicles' AND ancestry LIKE '%\"CAManBase\"%'")}
    # The snapshot has no value indexes; load each association once.
    by_ammo, mounted, feeds = {}, {}, {}
    for magazine, ammo in db.execute("SELECT magazine, ammo FROM magazine_ammo"):
        by_ammo.setdefault((ammo or "").lower(), []).append(magazine)
    for vehicle, path, kind, value in db.execute("SELECT vehicle, path, kind, value FROM mounts"):
        if vehicle.lower() not in men:
            mounted.setdefault((kind, value.lower()), []).append(f"{vehicle} {path}")
    for weapon, magazine in db.execute("SELECT DISTINCT weapon, magazine FROM weapon_magazines"):
        feeds.setdefault(magazine.lower(), set()).add(weapon)
    types = {name.lower(): value for name, value in db.execute(
        "SELECT classname, value FROM fields WHERE section='CfgWeapons' AND path='[\"type\"]'")}
    pylons = {name.lower() for (name,) in db.execute(
        "SELECT classname FROM fields WHERE section='CfgMagazines' AND path='[\"pylonWeapon\"]'")}
    db.close()
    result = {}
    for projectile in projectiles:
        magazines = by_ammo.get(projectile.lower(), [])
        blockers, weapons = set(), set()
        for magazine in magazines:
            if magazine.lower() in pylons:
                blockers.add(f"pylon magazine {magazine}")
            blockers.update(f"{where} lists {magazine}" for where in mounted.get(("magazine", magazine.lower()), []))
            weapons.update(feeds.get(magazine.lower(), ()))
        for weapon in weapons:
            kind = types.get(weapon.lower())
            if kind not in HANDHELD_TYPES:
                blockers.add(f"weapon {weapon} type {kind or 'missing'}")
            blockers.update(f"{where} mounts {weapon}" for where in mounted.get(("weapon", weapon.lower()), []))
        verdict = "no_magazines" if not magazines else "vehicle_shared" if blockers else "handheld_only"
        result[projectile.lower()] = {"classname": projectile, "verdict": verdict, "magazines": len(magazines),
                                      "weapons": len(weapons), "blockers": len(blockers),
                                      "examples": sorted(blockers)[:5]}
    return result


if __name__ == "__main__":
    report = classify(Path(sys.argv[1]), sys.argv[2:])
    print(json.dumps({"verdicts": dict(Counter(row["verdict"] for row in report.values())), "rows": list(report.values())}, indent=2))
