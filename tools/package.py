"""Build a small source distribution; runtimes, weights and personal data are excluded."""

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "dist/dantejp-windows.zip"
    output.parent.mkdir(exist_ok=True)
    files = [
        root / name
        for name in (
            "README.md",
            "AGENTS.md",
            "pyproject.toml",
            "uv.lock",
            ".python-version",
            ".gitignore",
        )
    ]
    files.extend(root.glob("*.cmd"))
    for folder in ("src", "tools", "tests", "engineering"):
        files.extend(
            p
            for p in (root / folder).rglob("*")
            if p.is_file() and p.suffix in (".py", ".ps1", ".md", ".json")
        )
    manifest = {}
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for path in sorted(files):
            if not path.resolve().is_relative_to(root):
                raise ValueError("Distribution file escapes the project directory.")
            name = path.relative_to(root).as_posix()
            content = path.read_bytes()
            manifest[name] = hashlib.sha256(content).hexdigest()
            archive.writestr("DanteJP/" + name, content)
        archive.writestr("DanteJP/MANIFEST.json", json.dumps(manifest, indent=2))
    print(f"Created {output} ({output.stat().st_size / 1e6:.2f} MB, {len(manifest)} files)")


if __name__ == "__main__":
    main()
