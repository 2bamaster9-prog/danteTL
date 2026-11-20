"""Explicit CLI model installation, sharing the in-app verified downloader."""

import argparse
import threading

from dantetl.languages.selection import DEFAULT_SOURCE, SOURCE_LANGUAGES
from dantetl.runtime.model_store import install_model, model_catalog
from dantetl.runtime.setup_values import ModelProgress


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--translation",
        action="store_true",
        help="Install the recommended translation model instead of OCR",
    )
    group.add_argument("--gemma", action="store_true", help="Install optional Gemma 4 E2B QAT")
    group.add_argument("--model", choices=tuple(bundle.key for bundle in model_catalog()))
    group.add_argument("--ocr-source", choices=SOURCE_LANGUAGES, help="Install OCR for this source")
    args = parser.parse_args()
    key = args.model or ("gemma" if args.gemma or args.translation else "ocr")
    source = SOURCE_LANGUAGES[args.ocr_source] if args.ocr_source else DEFAULT_SOURCE
    bundle = next(b for b in model_catalog(source) if b.key == key)
    previous = ""

    def progress(value: ModelProgress) -> None:
        nonlocal previous
        message = f"{value.message} · {value.received / max(1, value.total):.0%}"
        if message != previous:
            print(message, flush=True)
            previous = message

    install_model(bundle, progress, threading.Event())
    print(f"Models verified in {bundle.local_directory}. Inference works offline.", flush=True)


if __name__ == "__main__":
    main()
