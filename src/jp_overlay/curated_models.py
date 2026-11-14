"""Pinned optional GGUF choices, using the same bounded adapter as local imports."""

import hashlib
from dataclasses import dataclass

from jp_overlay.gguf_backend import GgufBackend
from jp_overlay.gguf_models import ImportedModel, inspect_gguf
from jp_overlay.model_store import ModelBundle
from jp_overlay.models import ModelAsset, validate_asset
from jp_overlay.paths import state_root


@dataclass(frozen=True, slots=True)
class CuratedModel:
    key: str
    name: str
    description: str
    architecture: str
    profile: str
    assets: tuple[ModelAsset, ...]

    def bundle(self) -> ModelBundle:
        return ModelBundle(
            self.key,
            self.name,
            state_root() / "models" / self.key,
            self.assets,
            self.description,
            language_model=True,
        )

    def load(self, device: str) -> GgufBackend:
        """Called on the translator worker; no registry entry or implicit download."""
        bundle = self.bundle()
        weights, *notices = self.assets
        for asset in notices:
            validate_asset(bundle.directory / asset.filename, asset, None)
        path = bundle.directory / weights.filename
        info = inspect_gguf(path, self.profile)
        if info.architecture != self.architecture:
            raise ValueError("Unexpected model architecture. Open Models → Verify / repair.")
        registration = ImportedModel(
            self.key,
            str(path),
            self.name,
            weights.sha256,
            weights.size,
            self.architecture,
            self.profile,
            hashlib.sha256(info.template.encode()).hexdigest(),
        )
        # The adapter checks the pinned weights hash before loading native inference.
        return GgufBackend(registration, device=device)


MODELS = (
    CuratedModel(
        "qwen35-4b",
        "Qwen3.5 4B · alternative dialogue model",
        "A 4B alternative for dialogue and context; compare its wording with Gemma. "
        "2.74 GB download, plus working memory. CPU works; GPU recommended for responsiveness. "
        "Unsloth Q4_K_M conversion of Qwen's model · Apache-2.0. "
        "Quality and speed vary by scene; no overall winner has been established.",
        "qwen35",
        "embedded",
        (
            ModelAsset(
                "unsloth/Qwen3.5-4B-GGUF",
                "e87f176479d0855a907a41277aca2f8ee7a09523",
                "Qwen3.5-4B-Q4_K_M.gguf",
                "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4",
                2740937888,
            ),
            ModelAsset(
                "unsloth/Qwen3.5-4B-GGUF",
                "e87f176479d0855a907a41277aca2f8ee7a09523",
                "README.md",
                "28546f5fc4f22ee1b3f17b908957f17fcfa66174032136265bdb27f404bc1e6c",
                78906,
            ),
        ),
    ),
    CuratedModel(
        "gemma-e4b",
        "Gemma 4 E4B · larger Gemma option",
        "A larger Gemma for users willing to spend more memory on translation. "
        "5.15 GB download, plus working memory; the largest model offered here. "
        "CPU works; GPU recommended for responsiveness. Google QAT Q4_0 · Apache-2.0. "
        "A quality upgrade to try, rather than a guaranteed winner over Qwen or E2B.",
        "gemma4",
        "gemma4",
        (
            ModelAsset(
                "google/gemma-4-E4B-it-qat-q4_0-gguf",
                "4b4a2c1d584be7264f87aac328a1bc739ce81b6c",
                "gemma-4-E4B_q4_0-it.gguf",
                "676c35070db6dbe52f93e9c864ee0fba4eddea94b9c875d9cb10daff453fbaee",
                5154941280,
            ),
            ModelAsset(
                "google/gemma-4-E4B-it-qat-q4_0-gguf",
                "4b4a2c1d584be7264f87aac328a1bc739ce81b6c",
                "README.md",
                "6c8dbc23d482d76d6a02e6804941fae6dccdcd20e6372c26e4dec35e21348607",
                29233,
            ),
        ),
    ),
)
