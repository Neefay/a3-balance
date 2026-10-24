# Tools

The balance pipeline. `a3bal.py` runs these scripts in the right order (see
[docs/MAKE_YOUR_OWN.md](../docs/MAKE_YOUR_OWN.md)); this page lists what each
one does, for running steps by hand or changing them. Run everything from this
folder with Python 3.11 or newer. There are no dependencies.

Generated folders (`data-recovered/`, `proposal/`, `validation/`, `audit/`,
`chart-data/`, `balance-pilot/`, `equipment.sqlite`) are git-ignored. Scripts
that write a capture or build refuse to overwrite an existing one.

## In-game scripts

| Script | Session | What it does |
|---|---|---|
| `export_configs.sqf` | 1, full modset | exports every relevant class with inherited values |
| `capture_remaining.template.sqf` | 2 and 3 | template for `capture_full.sqf` / `capture_clean.sqf`: magazine and mount use, vanilla references |
| `capture_clean_vanilla.template.sqf` | 3, vanilla | template for the anchor reference capture |
| `verify_balance_pilot.template.sqf` | 4 | config check, packed into the pilot |
| `acceptance_test.template.sqf` | 4 | shots-to-down damage test, packed into the pilot |
| `run_pilot_session.template.sqf` | 4 | runs the checks above from one console line |
| `range_test.template.sqf` | optional | before/after damage test without the pilot (`prepare_range_test.py`) |

## Import

| Script | Input | Output |
|---|---|---|
| `extract_rpt.py <rpt> <new dir> [--salvage]` | session 1 RPT | `configs.full.jsonl.gz`, `configs.relevant.jsonl`, `wearables.jsonl`, `ammo.csv`, `summary.json` |
| `inventory.py <dir>` | extracted folder | `wearables.csv`, `inventory.json` |
| `import_remaining_capture.py <rpt> <new dir>` | session 2 or 3 RPT | `snapshot.sqlite`, `records.jsonl.gz`, `import-report.json` |
| `import_clean_capture.py <rpt> <new file>` | session 3 RPT | vanilla anchor values (`validation/clean-vanilla-capture.json`) |
| `import_pilot_session.py <rpt> <new dir> [--pilot]` | session 4 RPT | `ACCEPTANCE.md`, `session-report.json`, trial CSVs |
| `import_range_test.py <rpt> <new dir>` | range test RPT | range test summary |

## Draft

| Script | What it does |
|---|---|
| `draft_balance.py <data> <out> [snapshot]` | the proposal: anchors, change ledger, coverage, wearable targets, ammunition mapping |
| `wearable_assessment.py` | classifies vests and uniforms (called by `draft_balance.py`) |
| `wearable_targets.py` | picks vest and uniform tiers and writes their edits (called by `draft_balance.py`) |
| `ammunition_policy.py` | cartridges, round types and the ammunition ladder (called by `draft_balance.py`) |
| `handheld_usage.py` | which rounds are fired by handheld weapons or vehicle MGs (called by `draft_balance.py`) |
| `audit_configs.py <data> <out>` | protection profiles and shared-model findings |
| `build_review_queue.py` | `proposal/UNRESOLVED_FAMILIES.md`, the gear left to identify |
| `build_query_db.py` | `equipment.sqlite` and `chart-data/` CSVs; see `queries.sql` |
| `make_example_chart.py` | an offline example chart over the database |

## Check and build

| Script | What it does |
|---|---|
| `prepare_remaining_captures.py` | writes the session 2 and 3 batch scripts |
| `prepare_clean_capture.py` | writes the session 3 anchor capture script |
| `compare_clean_baseline.py` | compares the vanilla captures with the modset's values |
| `prepare_acceptance_test.py` | writes the damage test for the pilot |
| `build_balance_pilot.py [folder]` | the test mod: every change, the config check and the damage test, in one PBO |
| `build_release.py <session> --hemtt` | writes `../addons/main/config.cpp` from a passed pilot |
| `build_release.py <session> --out <dir>` | packs an unsigned release without HEMTT |

`build_helmet_pilot.py`, `import_helmet_verification.py`,
`import_balance_verification.py` and `verify_helmet_pilot.template.sqf` are the
earlier helmet-only and two-part pilots. The current scripts reuse their PBO
packer and validators.

## Tests

```powershell
python -m unittest discover -q
```

The tests use small synthetic inputs and don't need any captured data.
