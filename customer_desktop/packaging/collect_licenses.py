"""Build a local dependency/version/license inventory, with bundled license text."""

from importlib.metadata import distributions
import json
from pathlib import Path
import sys

out = Path(sys.argv[1]) / "licenses"
out.mkdir(parents=True, exist_ok=True)
inventory = []
for dist in distributions():
    name = dist.metadata.get("Name", "unknown")
    inventory.append(
        dict(
            name=name,
            version=dist.version,
            license=dist.metadata.get("License-Expression")
            or dist.metadata.get("License", "See bundled license"),
            url=dist.metadata.get("Home-page", ""),
        )
    )
    for entry in dist.files or []:
        if any(
            part.lower().startswith(("license", "copying", "notice"))
            for part in entry.parts
        ):
            src = Path(dist.locate_file(entry))
            if src.is_file():
                target = out / name / str(entry)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(src.read_bytes())
(out / "inventory.json").write_text(
    json.dumps(sorted(inventory, key=lambda d: d["name"].lower()), indent=2),
    encoding="utf-8",
)
