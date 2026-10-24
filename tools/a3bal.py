"""One entry point for the balance pipeline. Each step runs the underlying scripts in order.

    python a3bal.py extract <export.rpt>        session 1 RPT: full config export -> data-recovered/
    python a3bal.py captures                    first draft, then the two capture scripts for sessions 2 and 3
    python a3bal.py import-captures --full <rpt> --clean <rpt>
    python a3bal.py pilot                       final draft, reference checks and the test pilot mod
    python a3bal.py session <pilot-session.rpt> import the one-line pilot session (PASS / NEEDS REVIEW)
    python a3bal.py release                     write ../addons/main/config.cpp for HEMTT

See docs/MAKE_YOUR_OWN.md. Steps never overwrite captured data; remove a folder to redo its step.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(*args):
    print(">", " ".join(str(a) for a in args), flush=True)
    result = subprocess.run([sys.executable, *map(str, args)], cwd=ROOT)
    if result.returncode:
        sys.exit(f"Step failed: {args[0]}")


def need(path, hint):
    if not (ROOT / path).exists():
        sys.exit(f"Missing {path}: {hint}")


def extract(a):
    run("extract_rpt.py", a.rpt.resolve(), "data-recovered", "--salvage")
    run("inventory.py", "data-recovered")
    run("audit_configs.py", "data-recovered", "audit")


def draft():
    need("data-recovered/configs.relevant.jsonl", "run `a3bal.py extract <export.rpt>` first")
    run("draft_balance.py", "data-recovered", "proposal")
    run("build_review_queue.py")


def captures(a):
    draft()
    run("prepare_remaining_captures.py")
    run("prepare_clean_capture.py")
    print("\nSession 2, full modset:  validation/remaining/capture_full.sqf")
    print("Session 3, vanilla only: validation/remaining/capture_clean.sqf, then validation/capture_clean_vanilla.sqf")


def import_captures(a):
    need("validation/remaining/manifest.json", "run `a3bal.py captures` first")
    run("import_remaining_capture.py", a.full.resolve(), "validation/remaining/full")
    run("import_remaining_capture.py", a.clean.resolve(), "validation/remaining/clean")
    run("import_clean_capture.py", a.clean.resolve(), "validation/clean-vanilla-capture.json")


def pilot(a):
    need("validation/remaining/full/snapshot.sqlite", "run `a3bal.py import-captures` first")
    need("validation/clean-vanilla-capture.json", "run `a3bal.py import-captures` first")
    draft()
    run("build_query_db.py")
    run("compare_clean_baseline.py")
    run("prepare_acceptance_test.py")
    run("build_balance_pilot.py", "balance-pilot")
    manifest = json.loads((ROOT / "balance-pilot/manifest.json").read_text())
    print(f"\nLoad {ROOT / 'balance-pilot' / '@A3Balance_Pilot'} with your modset, start an Eden preview and run:")
    print("    " + manifest["session"]["console_line"])


def session(a):
    need("balance-pilot/manifest.json", "run `a3bal.py pilot` first")
    run("import_pilot_session.py", a.rpt.resolve(), "validation/session", "--pilot", "balance-pilot")
    print("\nReport: validation/session/ACCEPTANCE.md")


def release(a):
    need("validation/session/session-report.json", "run `a3bal.py session <rpt>` first")
    run("build_release.py", "validation/session", "--pilot", "balance-pilot", "--hemtt")
    print("\nNow run `hemtt build` (test) or `hemtt release` (signed zip) in the repository root.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="step", required=True)
    sub.add_parser("extract").add_argument("rpt", type=Path)
    sub.add_parser("captures")
    p = sub.add_parser("import-captures")
    p.add_argument("--full", type=Path, required=True, help="RPT of session 2 (full modset)")
    p.add_argument("--clean", type=Path, required=True, help="RPT of session 3 (vanilla only)")
    sub.add_parser("pilot")
    sub.add_parser("session").add_argument("rpt", type=Path)
    sub.add_parser("release")
    args = parser.parse_args()
    {"extract": extract, "captures": captures, "import-captures": import_captures, "pilot": pilot,
     "session": session, "release": release}[args.step](args)
