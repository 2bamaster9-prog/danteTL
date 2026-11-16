"""Identity and offline installation input for the release's standard application wheel."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from packaging.utils import parse_wheel_filename


@dataclass(frozen=True, slots=True)
class ApplicationWheel:
    path: Path
    version: str
    sha256: str

    def requirements(self, target: Path) -> Path:
        """uv verifies the actual wheel bytes before installing; never resolve dependencies."""
        requirement = target / "application.txt"
        requirement.write_text(
            f"dantejp @ {self.path.as_uri()}#sha256={self.sha256} --hash=sha256:{self.sha256}\n",
            encoding="utf-8",
        )
        return requirement

    def installed_at(self, site: Path) -> bool:
        """Read standard installer provenance, without importing code from another runtime."""
        metadata = site / f"dantejp-{self.version}.dist-info/direct_url.json"
        try:
            provenance = json.loads(metadata.read_text("utf-8"))
            # uv retains a local URL's hash fragment; other installers record archive hashes.
            archive_hash = provenance.get("archive_info", {}).get("hashes", {}).get("sha256")
            url_hash = parse_qs(urlsplit(provenance.get("url", "")).fragment).get("sha256")
            return (archive_hash == self.sha256 or url_hash == [self.sha256]) and (
                site / "dantejp/__main__.py"
            ).is_file()
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return False


def bundled_application(project: Path) -> ApplicationWheel:
    """Small checksum reads are safe during readiness checks; installation owns byte hashing."""
    wheels = tuple((project / "application").glob("dantejp-*.whl"))
    if len(wheels) != 1:
        raise ValueError("The bundled app wheel is missing or ambiguous. Extract the complete ZIP.")
    wheel = wheels[0]
    name, version, _, tags = parse_wheel_filename(wheel.name)
    if name != "dantejp" or {str(tag) for tag in tags} != {"py3-none-any"}:
        raise ValueError("The bundled app wheel is invalid. Extract the complete ZIP.")
    checksum = wheel.with_suffix(".whl.sha256")
    if checksum.stat().st_size > 1024:
        raise ValueError("Invalid app wheel checksum.")
    expected = checksum.read_text("ascii").strip()
    match = re.fullmatch(r"([a-f0-9]{64})  " + re.escape(wheel.name), expected)
    if not match:
        raise ValueError("Invalid app wheel checksum. Extract the complete ZIP.")
    return ApplicationWheel(wheel.resolve(), str(version), match[1])
