"""Read bounded reference frames; refuse incomplete/modded captures and overwrite."""
import argparse
import json
from pathlib import Path
import re

from extract_rpt import parse_sqf

PREFIX = re.compile(rb"A3BALREF\|([^|\r\n]+)\|(\d+)\|")
FRAME = re.compile(rb"A3BALREF\|([^|\r\n]+)\|(\d+)\|(\d+)\|(\d+)\|(\[[0-9, ]*\])\|END")


def validate(records, manifest):
    if not records or records[0][:3] != ["BEGIN", 1, manifest["requests_sha256"]]:
        raise ValueError("Missing/mismatched BEGIN and request manifest")
    if records[-1][:3] != ["END", 1, manifest["requests_sha256"]] or records[-1][3] != len(records):
        raise ValueError("Incomplete capture or mismatched END count")
    if records[-1][4]:
        raise ValueError("Requested reference classes are missing")
    mods = records[0][4]
    if not mods or any(len(mod) < 4 or mod[3] is not True for mod in mods):
        raise ValueError("Capture contains non-official or unverifiable mods")
    expected = {(section, name): fields for section, name, fields in manifest["requests"]}
    classes, fields = {}, {}
    for record in records[1:-1]:
        kind = record[0]
        key = tuple(record[1:3])
        if key not in expected:
            raise ValueError("Unexpected captured class")
        if kind == "CLASS":
            if key in classes:
                raise ValueError("Duplicate captured class")
            classes[key] = record
        elif kind == "FIELD":
            path = tuple(record[3])
            field_key = (*key, path)
            if not path or path[0] not in expected[key] or field_key in fields:
                raise ValueError("Unexpected/duplicate field path")
            if record[4] not in {"number", "text", "array", "missing"}:
                raise ValueError("Unknown field type")
            fields[field_key] = record
        else:
            raise ValueError("Unexpected capture record")
    if set(classes) != set(expected):
        raise ValueError("Captured reference class set is incomplete")
    for key, requested in expected.items():
        observed = {path[0] for section, name, path in fields if (section, name) == key}
        if set(requested) != observed:
            raise ValueError("Requested field roots are incomplete")
    return {"manifest_sha256": manifest["requests_sha256"], "product_version": records[0][3],
            "loaded_mods": mods, "classes": list(classes.values()), "fields": list(fields.values())}


def read_records(rpt, run=None, marker=b"A3BALREF"):
    frame_pattern = re.compile(re.escape(marker) + rb"\|([^|\r\n]+)\|(\d+)\|(\d+)\|(\d+)\|(\[[0-9, ]*\])\|END")
    prefix_pattern = re.compile(re.escape(marker) + rb"\|([^|\r\n]+)\|(\d+)\|")
    runs = {}
    damaged = {}
    with rpt.open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            match = frame_pattern.search(line)
            if not match:
                prefix = prefix_pattern.search(line)
                if prefix:
                    identity = prefix[1].decode("ascii")
                    if run is None or identity == run:
                        damaged.setdefault(identity, []).append((line_number, int(prefix[2])))
                continue
            identity, record, part, total, payload = match.groups()
            identity = identity.decode("ascii")
            if run is not None and identity != run:
                continue
            record, part, total = int(record), int(part), int(total)
            if not 1 <= record <= 100000 or not 1 <= part <= total <= 10000:
                raise ValueError("Invalid frame part")
            entry = runs.setdefault(identity, {}).setdefault(record, {"total": total, "parts": {}})
            if entry["total"] != total or part in entry["parts"]:
                raise ValueError("Inconsistent or duplicate frame")
            entry["parts"][part] = json.loads(payload)
    identities = set(runs) | set(damaged)
    if not identities:
        raise ValueError(f"No {marker.decode('ascii')} capture frames found. Check the RPT for addon-loading or preflight-refusal messages.")
    if len(identities) != 1:
        raise ValueError("Specify --run if the RPT contains multiple captures; exactly one capture is required")
    identity = next(iter(identities))
    if identity in damaged:
        lines = ", ".join(str(number) for number, _ in damaged[identity][:8])
        records = sorted({number for _, number in damaged[identity]})
        script = "validation/capture_clean_vanilla.sqf" if marker == b"A3BALREF" else "helmet-pilot/verify_helmet_pilot.sqf"
        raise ValueError(f"Truncated/malformed capture frames in run {identity}, RPT lines {lines}, records {records}. "
                         f"Re-copy and rerun {script} (96-character chunks); "
                         "then import the new run using --run. The incomplete capture was not imported.")
    identity, frames = next(iter(runs.items()))
    if sorted(frames) != list(range(1, len(frames) + 1)):
        raise ValueError("Missing record numbers")
    records = []
    for entry in frames.values():
        if len(entry["parts"]) != entry["total"]:
            raise ValueError("Incomplete frame")
    for index in sorted(frames):
        entry = frames[index]
        source = "".join(chr(c) for part in range(1, entry["total"] + 1) for c in entry["parts"][part])
        records.append(parse_sqf(source))
    return identity, records


def read_capture(rpt, manifest, run=None):
    identity, records = read_records(rpt, run)
    return {"run": identity, **validate(records, manifest)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("rpt", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--run")
    args = parser.parse_args()
    manifest_path = Path(__file__).resolve().parent / "validation/clean_capture_manifest.json"
    result = read_capture(args.rpt, json.loads(manifest_path.read_text()), args.run)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"output": str(args.output), "run": result["run"], "classes": len(result["classes"])}))
