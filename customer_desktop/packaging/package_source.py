"""Corresponding source archive from the current working tree, never .git or customer data."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

root = Path(__file__).resolve().parents[2]
out = Path(sys.argv[1]) / "source"
out.mkdir(parents=True, exist_ok=True)
files = {
    Path(p)
    for p in subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    .decode("utf-8")
    .split("\0")
    if p
}
for base in ("customer_desktop", "tests/unit/customer_desktop"):
    files.update(
        p.relative_to(root)
        for p in (root / base).rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix not in (".pyc", ".pyo")
    )
files.add(Path("requirements-desktop.txt"))
# Include new regression code and anonymized XML captures before they are tracked.
for pattern in ("*.py", "*.xml", "*.json", "*.md"):
    files.update(
        p.relative_to(root)
        for p in (root / "tests/unit").rglob(pattern)
        if "__pycache__" not in p.parts
    )
# New engine modules can still be untracked in a review build. Include their
# Source and runtime data as well; a Git-only list would omit new selector YAML.
for base in ("taktik", "bridges"):
    for pattern in ("*.py", "*.json", "*.yaml", "*.yml"):
        files.update(
            p.relative_to(root)
            for p in (root / base).rglob(pattern)
            if "__pycache__" not in p.parts
        )
manifest = {}
with zipfile.ZipFile(
    out / "TAKTIK-corresponding-source.zip", "w", zipfile.ZIP_DEFLATED
) as archive:
    for relative in sorted(files):
        if (
            relative.parts[0] == "admin"
            or relative.suffix.lower() in (".dpapi", ".pem", ".key")
            or relative.name in ("license-clock.bin", "license.key")
        ):
            continue
        if not (root / relative).is_file():
            continue
        data = (root / relative).read_bytes()
        archive.writestr(relative.as_posix(), data)
        manifest[relative.as_posix()] = hashlib.sha256(data).hexdigest()
    archive.writestr("SOURCE-MANIFEST.json", json.dumps(manifest, indent=2))
(out / "README.txt").write_text(
    "Source snapshot for this local Windows build. Extract, install packaging/build-environment.lock into Python 3.10 on Windows, then run customer_desktop/packaging/build.ps1. No Git metadata or customer runtime data is included.\n",
    encoding="utf-8",
)
print("Packaged corresponding source:", out / "TAKTIK-corresponding-source.zip")
