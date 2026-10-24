"""Package the release from a balance pilot whose in-game session passed.

Usage: python build_release.py <session_result_dir> [--pilot balance-pilot] --hemtt
           writes ../addons/main/config.cpp and ../release.json for `hemtt build` / `hemtt release`
       python build_release.py <session_result_dir> [--pilot balance-pilot] [--out release]
           packs an unsigned release/@A3Balance without HEMTT
       python build_release.py --candidate <folder>   (unverified release candidate, for review only)
The release config is the pilot's verified config with only the CfgPatches header renamed; the
test scripts stay out.
"""
import argparse
import hashlib
import json
from pathlib import Path

from build_helmet_pilot import pack_files

ADDON = "a3bal_main"
MOD = "@A3Balance"
PILOT_HEADER = ['    class a3bal_pilot', '        name = "A3 Balance Pilot";']
RELEASE_HEADER = [f'    class {ADDON}', '        name = "A3 Balance";']


def release_config(pilot_config):
    lines = pilot_config.split("\n")
    end = lines.index("class CfgWeapons")
    header = lines[:end]
    if any(header.count(line) != 1 for line in PILOT_HEADER):
        raise ValueError("Unexpected pilot CfgPatches header")
    renamed = [RELEASE_HEADER[PILOT_HEADER.index(line)] if line in PILOT_HEADER else line for line in header]
    renamed[0] = "// A3 Balance: helmets, vests, uniform units and ammunition normalized to the vanilla ladder."
    return "\n".join(renamed + lines[end:])


def verified(pilot_folder, session):
    manifest = json.loads((pilot_folder / "manifest.json").read_text())
    if session is not None:
        report = json.loads((session / "session-report.json").read_text())
        if not report["passed"] or report["pilot_build_id"] != manifest["build_id"]:
            raise ValueError("The session did not pass for this pilot build; no release is built")
    config = (pilot_folder / "source/a3bal_pilot/config.cpp").read_bytes()
    if hashlib.sha256(config).hexdigest() != manifest["config_sha256"]:
        raise ValueError("Pilot config differs from its manifest")
    text = release_config(config.decode("utf-8"))
    if text.split("\nclass CfgWeapons", 1)[1] != config.decode("utf-8").split("\nclass CfgWeapons", 1)[1]:
        raise ValueError("Release config body differs from the verified pilot")
    return text.encode("utf-8"), manifest


def info(manifest, session, data, **extra):
    return {"addon": ADDON, "status": "verified in game" if session is not None else "CANDIDATE: not verified in game; do not distribute",
            "pilot_build_id": manifest["build_id"], "session": Path(session).name if session is not None else None,
            **extra, "config_sha256": hashlib.sha256(data).hexdigest(),
            "verified_pilot_config_sha256": manifest["config_sha256"], "required_addons": len(manifest["required_addons"]),
            "changed_fields": manifest["changed_fields"], "by_kind": {k: v for k, v in manifest["by_kind"].items() if not k.startswith("Cfg")}}


def build(root, pilot_folder, out, session=None):
    data, manifest = verified(pilot_folder, session)
    if out.exists():
        raise ValueError(f"{out} already exists; refusing to overwrite a release")
    archive = pack_files([("config.cpp", data)], ADDON)
    mod = out / MOD
    (mod / "addons").mkdir(parents=True)
    (mod / f"addons/{ADDON}.pbo").write_bytes(archive)
    (mod / "mod.cpp").write_text('name = "A3 Balance";\ndescription = "Normalizes mod helmets, vests, uniforms and rifle ammunition to the vanilla ladder";\n', encoding="utf-8")
    (mod / "README.md").write_text((root / "release_README.md").read_text(encoding="utf-8"), encoding="utf-8")
    result = info(manifest, session, data, pbo_sha256=hashlib.sha256(archive).hexdigest(), signed=False)
    (out / "release.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def write_hemtt(root, pilot_folder, session):
    """Write the verified config into the HEMTT project; HEMTT builds and signs the PBO."""
    data, manifest = verified(pilot_folder, session)
    project = root.parent
    if not (project / ".hemtt/project.toml").exists():
        raise ValueError(f"No HEMTT project at {project}")
    # HEMTT's config parser rejects no-break spaces; they only occur inside display strings.
    nbsp = data.count(" ".encode())
    data = data.replace(" ".encode(), b" ")
    (project / "addons/main/config.cpp").write_bytes(data)
    result = info(manifest, session, data, built_with="hemtt", no_break_spaces_replaced=nbsp)
    (project / "release.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("session", type=Path, nargs="?")
    parser.add_argument("--pilot", default="balance-pilot")
    parser.add_argument("--out", type=Path, default=Path("release"))
    parser.add_argument("--hemtt", action="store_true", help="write the config into ../addons/main for HEMTT")
    parser.add_argument("--candidate", type=Path, help="build an unverified candidate into this folder instead")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if (args.session is None) == (args.candidate is None):
        parser.error("give a passed session result directory, or --candidate <folder>")
    if args.hemtt:
        if args.candidate:
            parser.error("--hemtt needs a passed session")
        print(json.dumps(write_hemtt(root, root / args.pilot, args.session), indent=2))
    else:
        out = args.candidate if args.candidate else root / args.out
        print(json.dumps(build(root, root / args.pilot, out, None if args.candidate else args.session), indent=2))
