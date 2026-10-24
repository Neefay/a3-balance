"""Generate a bounded reference capture from the current anchor list."""
import hashlib
import json
from pathlib import Path


def prepare(root):
    anchors = json.loads((root / "proposal/anchors.json").read_text())
    requests = []
    for row in anchors:
        fields = ["displayName", "scope", "ItemInfo"] if row["section"] == "CfgWeapons" else [
            "hit", "caliber", "typicalSpeed", "airFriction", "explosive", "indirectHit", "simulation"]
        requests.append([row["section"], row["classname"], fields])
        if row.get("unitClass"):
            requests.append(["CfgVehicles", row["unitClass"], ["armor", "armorStructural", "explosionShielding", "damageResistance", "impactDamageMultiplier", "HitPoints"]])
    assert len({(section.lower(), name.lower()) for section, name, _ in requests}) == len(requests)
    payload = json.dumps(requests, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    manifest = {"version": 1, "requests_sha256": digest, "requests": requests}
    destination = root / "validation"
    destination.mkdir(exist_ok=True)
    (destination / "clean_capture_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    template = (root / "capture_clean_vanilla.template.sqf").read_text()
    script = template.replace("__MANIFEST_SHA256__", digest).replace("__REQUESTS__", payload)
    assert "__REQUESTS__" not in script and "__MANIFEST_SHA256__" not in script
    (destination / "capture_clean_vanilla.sqf").write_text(script, encoding="utf-8")
    return {"classes": len(requests), "manifest_sha256": digest, "script": str(destination / "capture_clean_vanilla.sqf")}


if __name__ == "__main__":
    print(json.dumps(prepare(Path(__file__).resolve().parent), indent=2))
