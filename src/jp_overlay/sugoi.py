"""Pinned Sugoi V4 assets and the local CTranslate2/SentencePiece backend."""

import os
from pathlib import Path

from jp_overlay.models import ModelAsset, validate_asset
from jp_overlay.paths import state_root

REVISION = "71d67eb8e73ec2f5aaefc0689e03a4eb843d3a2b"
ASSETS = tuple(
    ModelAsset("entai2965/sugoi-v4-ja-en-ctranslate2", REVISION, name, digest, size)
    for name, size, digest in (
        (
            "model.bin",
            1102425134,
            "de9bbeeb1b74716536c08a82e44d4ce1950b3cf690c4a426f6ce44a6c1c17a3d",
        ),
        ("config.json", 222, "3e732fbc16f7155d1354f96e746092f95f290d6b0a0cac56e9e4a1dd7ddb13d2"),
        (
            "source_vocabulary.json",
            701538,
            "1ae20a6f46611cfd6766fc9dd289747ec835aebbc27a161c1ab4bd311912af4c",
        ),
        (
            "target_vocabulary.json",
            501642,
            "ad53ade1465d0752842772e1e1d5c5eb870afb9b42de99a8a23442008a4a35e8",
        ),
        (
            "spm/spm.ja.nopretok.model",
            785276,
            "1bff3529a8e0bd898f00707a4e36dc16540d84112cc8a4a14462c0099e4aab9d",
        ),
        (
            "spm/spm.en.nopretok.model",
            751435,
            "183aad11f5fa48b21fdbbb7a97082d160b86cbcc4f9dc5e61d0eebd48390d36a",
        ),
        ("LICENSE", 2949, "f028708b8b8b137b68b5196d38a76c43871945a77f041def5b9c2965ec49943a"),
        ("README.md", 3113, "7c1f037edddab82ce615b3ffa8261ecd185a3bfa30a312ee079b907553f19f52"),
    )
)


def model_directory() -> Path:
    override = os.environ.get("JP_OVERLAY_SUGOI_DIR")
    return Path(override) if override else state_root() / "models" / "sugoi-v4"


class SugoiBackend:
    """Only this adapter knows model paths, tokenization, and CTranslate2 options."""

    def __init__(self, directory: Path, *, threads: int = 2, beam_size: int = 2) -> None:
        for asset in ASSETS:
            validate_asset(directory / asset.filename, asset, "Setup Translation.cmd")
        import ctranslate2
        import sentencepiece

        self.cache_identity = (
            f"sugoi-v4:{REVISION}:ja-en:ct2-{ctranslate2.__version__}:"
            f"cpu-int8:spm-{sentencepiece.__version__}:beam{beam_size}:max256:v1"
        )
        self._beam_size = beam_size
        self._source = sentencepiece.SentencePieceProcessor(
            model_file=str(directory / "spm/spm.ja.nopretok.model")
        )
        self._target = sentencepiece.SentencePieceProcessor(
            model_file=str(directory / "spm/spm.en.nopretok.model")
        )
        self._translator = ctranslate2.Translator(
            str(directory),
            device="cpu",
            compute_type="int8",
            inter_threads=1,
            intra_threads=threads,
            max_queued_batches=1,
        )

    def translate(self, texts: tuple[str, ...]) -> tuple[str, ...]:
        tokens = [self._source.encode(text, out_type=str) for text in texts]
        if any(len(source) > 512 for source in tokens):
            raise ValueError("A source line exceeds Sugoi's 512-token input limit.")
        results = self._translator.translate_batch(
            tokens,
            beam_size=self._beam_size,
            max_batch_size=4,
            max_input_length=0,
            max_decoding_length=256,
            return_end_token=True,
        )
        output = []
        for result in results:
            hypothesis = result.hypotheses[0]
            if not hypothesis or hypothesis[-1] != "</s>":
                raise RuntimeError(
                    "Sugoi reached its output limit; refusing an incomplete translation."
                )
            # Preserve unknown markers for inspection instead of silently deleting source content.
            text = self._target.decode(hypothesis[:-1]).strip()
            if not text:
                raise RuntimeError("Sugoi returned an empty translation.")
            output.append(text)
        return tuple(output)

    def close(self) -> None:
        self._translator.unload_model()
