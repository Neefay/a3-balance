# A3 Balance

A config-only Arma 3 patch that puts mod helmets, vests, uniforms and rifle
ammunition on **vanilla Arma's protection and damage ladder**. A 6B3 protects
like vanilla's Carrier Rig, an M855 hits like vanilla's 5.56 ball, and a BromA
helmet is no tougher than an RHS one of the same type. Items keep their tier: a
light carrier is still lighter than a heavy plate.

This repository holds two things:

- **The patch** for one modset (RHS, 3CB, BromA, S&S, RoN, ACE, KAT and
  friends): one small compat addon per mod, about 130 KB together, built with
  [HEMTT](https://hemtt.dev).
- **The pipeline that made it.** Point it at your own modset and it builds a
  patch for that: export the configs, classify every item, draft the changes,
  build a test mod, check it in one Arma session, then release.

| | Items changed | They take vanilla's |
|---|---:|---|
| Helmets | 1,026 | light 4, combat 6, crew 8, heavy visored 10, aircrew 6/8, hard hat 2 |
| Vests | 1,656 | load-bearing 0, flak 12, light carrier 16, plate 20, heavy plate 24 |
| Uniforms | 753 | combat uniform or civilian clothing body values |
| Rifle rounds | 104 | 5.45x39, 5.56x45, 7.62x39, 7.62x51, 7.62x54R ball, with AP/enhanced/match on a ladder above it |

In total 20,013 values change. Mass, capacity, models, ACE and KAT medical are
untouched. [How it works](docs/HOW_IT_WORKS.md) has the full rules.

## How it patches

- **Only the numbers that change**, written once at the class that defines
  them, so inheritance carries them. 20,013 values take 2,113 lines.
- **Classes are reopened, not replaced.** Every class keeps its parent and
  everything the patch doesn't name, so the mod authors' own updates still come
  through.
- **One addon per mod, depending only on that mod.** Each sets
  `skipWhenMissingDependencies`, so the patch works with any subset of the mods.
- **Proven before it's built.** A model of the whole loaded config shows that
  every target gets its value, nothing else moves, and no class changes parent.
  [Parent classes](docs/HOW_IT_WORKS.md#parent-classes) explains why that last
  check matters.

## Status

The balance itself was tested in game on 2026-10-24. With it, 7.62 gets through
a plate in 2 to 3 shots and 5.56 in about 9, as in vanilla, where mod plates used
to stop 12 or more. In 110 of 110 checks, patched gear and rounds took the same
shots as their vanilla equivalent ([results](docs/results/)).

That test used an earlier single-file build. It copied whole protection blocks,
required 179 addons, and changed the parent of 18 classes. The per-mod build here
replaces it. On the same captures it reproduces all 52,743 protection and
ammunition values the earlier build passed in game. It has not had its own
session yet, so `release.json` marks it as a candidate until it does.

## Use the patch

- Everyone loads it: players, server and headless clients.
- Each addon only loads with its mod, but the values were drafted for this
  modset's versions. Rebuild after RHS, 3CB, BromA, S&S, RoN or ACE update.
- Unload the mod to revert. Saves and missions are not affected.

## Build it

```powershell
hemtt build      # test build: .hemttout/build/addons/a3bal_*.pbo
hemtt release    # signed build and zip: .hemttout/release, releases/
```

[docs/BUILDING.md](docs/BUILDING.md) covers installing HEMTT, signing with your
own key, and packing without HEMTT.

## Make your own

You need Arma 3 with your modset, Python 3.11 or newer (no packages), and four
Arma sessions: three captures and one test. The short version:

```powershell
cd tools
python a3bal.py extract <session1.rpt>    # session 1 runs export_configs.sqf
python a3bal.py captures                  # writes the scripts for sessions 2 and 3
python a3bal.py import-captures --full <session2.rpt> --clean <session3.rpt>
python a3bal.py pilot                     # builds the patches and the test mod
python a3bal.py session <session4.rpt>    # PASS or NEEDS REVIEW
python a3bal.py release                   # writes addons/<mod>/config.cpp
cd ..
hemtt release
```

[docs/MAKE_YOUR_OWN.md](docs/MAKE_YOUR_OWN.md) walks through every step,
explains what each session does, and shows where to change the tiers.
[tools/README.md](tools/README.md) lists every script.

## Repository layout

| Path | Contents |
|---|---|
| `addons/<mod>/` | one generated patch per mod, built by HEMTT |
| `addons/main/` | the mod's name and version |
| `.hemtt/` | HEMTT project settings |
| `tools/` | the pipeline: Python scripts, in-game SQF scripts, tests |
| `docs/` | how it works, building, making your own, test results |
| `reference/` | the change ledger: every changed value with its old value |
| `release.json` | provenance of the current patches: pilot build ID and hashes |
| `extras/` | not part of the build |

## License

[MIT](LICENSE). The patches name other mods' classes and set values on them;
they contain none of those mods' models, textures, scripts or other values, and
those mods remain their authors' work.
