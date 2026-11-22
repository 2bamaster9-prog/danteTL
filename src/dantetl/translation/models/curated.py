"""Pinned optional GGUF choices, using the same bounded adapter as local imports."""

import hashlib
from dataclasses import dataclass

from dantetl.i18n import CatalogText, mark, tr
from dantetl.languages.selection import DEFAULT_SOURCE
from dantetl.languages.source import SourceLanguage
from dantetl.paths import state_root
from dantetl.runtime.assets import ModelAsset, validate_asset
from dantetl.runtime.model_store import ModelBundle
from dantetl.translation.backends.gguf import GgufBackend
from dantetl.translation.models.gguf import inspect_gguf
from dantetl.translation.models.values import ImportedModel


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
            CatalogText(self.name),
            state_root() / "models" / self.key,
            self.assets,
            CatalogText(self.description),
            language_model=True,
            needs_plamo=self.profile == "plamo3",
        )

    def load(self, device: str, *, language: SourceLanguage = DEFAULT_SOURCE) -> GgufBackend:
        """Called on the translator worker; no registry entry or implicit download."""
        bundle = self.bundle()
        weights, *notices = self.assets
        for asset in notices:
            validate_asset(bundle.directory / asset.filename, asset, None)
        path = bundle.directory / weights.filename
        info = inspect_gguf(path, self.profile)
        if info.architecture != self.architecture:
            raise ValueError(tr("Unexpected model architecture. Open Models → Verify / repair."))
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
        return GgufBackend(registration, device=device, language=language)


MODELS = (
    CuratedModel(
        "gemma-e4b",
        mark("Gemma 4 E4B · Higher-resource recommendation"),
        mark("Recommended when more memory is available; good game terminology."),
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
    CuratedModel(
        "plamo-2b",
        mark("PLaMo 3 Translate 2B · Dialogue alternative"),
        mark("Fast dialogue translation; unreliable for game stats and terminology."),
        "plamo3",
        "plamo3",
        (
            ModelAsset(
                "pfnet/plamo-3-translate-2b-GGUF",
                "4f672106b847200bfdc0f6af6c321cd94eba1aed",
                "plamo-3-translate-2b-Q4_K_M.gguf",
                "1ffd9073afcc70e35ccc942428aa2b73d7aa2b9ea779bf504b775369e0276c13",
                1807203040,
            ),
            ModelAsset(
                "pfnet/plamo-3-translate-2b-GGUF",
                "4f672106b847200bfdc0f6af6c321cd94eba1aed",
                "README.md",
                "020cfdf300bdbbbb4e314933c86968e71de2151d2f24ce6c4e89632004629859",
                45514,
            ),
        ),
    ),
    CuratedModel(
        "plamo-0.8b",
        mark("PLaMo 3 Translate 0.8B · Lightweight alternative"),
        mark("Very small and fast; weaker wording and unreliable game terminology."),
        "plamo3",
        "plamo3",
        (
            ModelAsset(
                "pfnet/plamo-3-translate-0.8b-GGUF",
                "1cf96ae02133958a20074bfdfab76517bb737d00",
                "plamo-3-translate-0.8b-Q4_K_M.gguf",
                "70891ec70dc7ab4205745a38307867c2881b99239f20327927633abfe4bc9ec6",
                573126848,
            ),
            ModelAsset(
                "pfnet/plamo-3-translate-0.8b-GGUF",
                "1cf96ae02133958a20074bfdfab76517bb737d00",
                "README.md",
                "bed9e42001f64cef73b8c5c236d9eaf73eae3eddfdfa694e8cce99bf285420bb",
                45558,
            ),
        ),
    ),
    CuratedModel(
        "qwen35-4b",
        mark("Qwen3.5 4B · Slower alternative"),
        mark("Useful translations, but noticeably slower than Gemma in this app."),
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
)
