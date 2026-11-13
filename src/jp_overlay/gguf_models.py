"""Bounded GGUF inspection and local registrations; never executes model code or downloads."""

import hashlib
import json
import os
import re
import struct
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

from jp_overlay.model_store import Cancelled, ModelProgress, Progress
from jp_overlay.paths import state_root

PROFILES = {
    "auto": "Automatic (recommended)",
    "embedded": "Embedded chat template",
    "gemma4": "Gemma 4",
    "chatml": "ChatML",
    "llama3": "Llama 3",
}


@dataclass(frozen=True, slots=True)
class GgufInfo:
    name: str
    architecture: str
    template: str
    size: int
    profile: str


class _Reader:
    """Skip vocabulary arrays without retaining them; cap metadata work and string sizes."""

    def __init__(self, stream: BinaryIO, size: int) -> None:
        self.stream, self.size = stream, size

    def read(self, count: int) -> bytes:
        if count < 0 or self.stream.tell() + count > min(self.size, 64 * 2**20):
            raise ValueError("GGUF metadata is truncated or exceeds the supported size.")
        data = self.stream.read(count)
        if len(data) != count:
            raise ValueError("Truncated GGUF file.")
        return data

    def number(self, fmt: str) -> int:
        return struct.unpack("<" + fmt, self.read(struct.calcsize(fmt)))[0]

    def string(self, *, keep: bool = True) -> str:
        length = self.number("Q")
        if length > 262_144:
            raise ValueError("GGUF metadata string is too large.")
        data = self.read(length)
        return data.decode("utf-8") if keep else ""

    def value(self, kind: int, keep: bool = False) -> str | int | None:
        widths = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
        if kind == 8:
            return self.string(keep=keep)
        if kind == 9:
            subtype, length = self.number("I"), self.number("Q")
            if length > 1_000_000 or subtype not in (*widths, 8):
                raise ValueError("Unsupported GGUF metadata array.")
            if subtype == 8:
                for _ in range(length):
                    self.string(keep=False)
            else:
                self.read(length * widths[subtype])
            return None
        if kind not in widths:
            raise ValueError("Unsupported GGUF metadata value.")
        data = self.read(widths[kind])
        return int.from_bytes(data, "little") if keep else None


def inspect_gguf(path: Path, profile: str = "auto") -> GgufInfo:
    if profile not in PROFILES:
        raise ValueError("Unknown prompt profile.")
    size = path.stat().st_size
    if not path.is_file() or path.suffix.lower() != ".gguf" or not 24 <= size <= 32 * 2**30:
        raise ValueError("Choose one complete GGUF language model (up to 32 GiB).")
    metadata: dict[str, str | int | None] = {}
    wanted = {"general.name", "general.architecture", "tokenizer.chat_template", "split.count"}
    with path.open("rb") as stream:
        reader = _Reader(stream, size)
        if reader.read(4) != b"GGUF" or reader.number("I") not in (2, 3):
            raise ValueError("This is not a supported GGUF v2/v3 file.")
        tensors, count = reader.number("Q"), reader.number("Q")
        if not 1 <= tensors <= 100_000 or count > 100_000:
            raise ValueError("This is not a complete language model.")
        for _ in range(count):
            key = reader.string()
            value = reader.value(reader.number("I"), keep=key in wanted)
            if key in wanted:
                if key in metadata:
                    raise ValueError("Duplicate GGUF metadata field.")
                metadata[key] = value
    if metadata.get("split.count", 1) != 1:
        raise ValueError("Split GGUF models are not supported yet. Choose a single-file version.")
    architecture = metadata.get("general.architecture")
    if not isinstance(architecture, str) or not re.fullmatch(r"[a-z0-9_-]{1,64}", architecture):
        raise ValueError("Missing or invalid model architecture.")
    if any(term in architecture for term in ("bert", "clip", "embedding")):
        raise ValueError("Choose a text-generation model, not an embedding or vision projector.")
    template = metadata.get("tokenizer.chat_template", "")
    if not isinstance(template, str) or len(template) > 65_536:
        raise ValueError("The embedded chat template is unsupported.")
    if "source_lang_code" in template:
        raise ValueError(
            "TranslateGemma needs a specialized translation profile; it is not supported yet."
        )
    if profile == "auto":
        profile = "gemma4" if architecture == "gemma4" else "embedded"
    if profile == "gemma4" and architecture != "gemma4":
        raise ValueError("The Gemma 4 profile requires a Gemma 4 model.")
    if profile == "embedded" and not template:
        raise ValueError("No embedded chat template. Select the model's documented prompt profile.")
    name = metadata.get("general.name") or path.stem
    name = " ".join(str(name).split())[:100]
    return GgufInfo(name, architecture, template, size, profile)


def fingerprint(path: Path, progress: Progress, cancel: threading.Event) -> tuple[str, int]:
    before = path.stat()
    digest, received = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(4 * 2**20):
            if cancel.is_set():
                raise Cancelled()
            digest.update(chunk)
            received += len(chunk)
            progress(ModelProgress("Checking local model…", received, before.st_size))
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(
            "The model changed while it was being checked. Retry after copying finishes."
        )
    return digest.hexdigest(), received


@dataclass(frozen=True, slots=True)
class ImportedModel:
    key: str
    path: str
    name: str
    sha256: str
    size: int
    architecture: str
    profile: str
    template_hash: str

    def available(self) -> bool:
        try:
            return Path(self.path).is_file() and Path(self.path).stat().st_size == self.size
        except OSError:
            return False


def describe(
    path: Path, profile: str, progress: Progress, cancel: threading.Event
) -> ImportedModel:
    path = path.resolve(strict=True)
    info = inspect_gguf(path, profile)
    digest, size = fingerprint(path, progress, cancel)
    template_hash = hashlib.sha256(info.template.encode()).hexdigest()
    identity = hashlib.sha256(f"{digest}:{info.profile}:{template_hash}".encode()).hexdigest()
    return ImportedModel(
        "imported-" + identity,
        str(path),
        info.name,
        digest,
        size,
        info.architecture,
        info.profile,
        template_hash,
    )


def registry_path() -> Path:
    return state_root() / "data/imported-models.json"


def read_registry(path: Path | None = None) -> tuple[ImportedModel, ...]:
    path = path or registry_path()
    if not path.exists():
        return ()
    if path.stat().st_size > 262_144:
        raise ValueError("Imported model list is too large.")
    data = json.loads(path.read_text("utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Unsupported imported model list.")
    entries = data.get("models")
    if not isinstance(entries, list) or len(entries) > 32:
        raise ValueError("Imported model list must contain at most 32 models.")
    models = []
    for entry in entries:
        try:
            model = ImportedModel(**entry)
            if (
                not re.fullmatch(r"imported-[0-9a-f]{64}", model.key)
                or not re.fullmatch(r"[0-9a-f]{64}", model.sha256)
                or not re.fullmatch(r"[0-9a-f]{64}", model.template_hash)
                or model.profile not in PROFILES
                or model.profile == "auto"
                or not Path(model.path).is_absolute()
                or len(model.path) > 4096
                or not isinstance(model.name, str)
                or not 1 <= len(model.name) <= 100
                or not isinstance(model.size, int)
                or not 24 <= model.size <= 32 * 2**30
                or not re.fullmatch(r"[a-z0-9_-]{1,64}", model.architecture)
            ):
                raise ValueError("Invalid imported model registration.")
        except (TypeError, KeyError) as error:
            raise ValueError("Invalid imported model registration.") from error
        if any(m.key == model.key for m in models):
            raise ValueError("Duplicate imported model registration.")
        models.append(model)
    return tuple(models)


def save_registration(
    model: ImportedModel, *, remove: bool = False, path: Path | None = None
) -> None:
    """Called on the setup worker. Files remain owned by the user, including on removal."""
    path = path or registry_path()
    models = [m for m in read_registry(path) if m.key != model.key]
    if not remove:
        models.append(model)
    if len(models) > 32:
        raise ValueError("Remove an imported model before adding another (limit 32).")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps({"version": 1, "models": [asdict(m) for m in models]}), "utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
