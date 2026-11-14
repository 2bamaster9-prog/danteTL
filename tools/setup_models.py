"""Explicit CLI model installation, sharing the in-app verified downloader."""

import argparse
import threading

from jp_overlay.model_store import ModelProgress, install_model, model_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--translation", action="store_true", help="Install Sugoi instead of OCR")
    group.add_argument("--gemma", action="store_true", help="Install optional Gemma 4 E2B QAT")
    group.add_argument("--model", choices=tuple(bundle.key for bundle in model_catalog()))
    args = parser.parse_args()
    key = args.model or ("gemma" if args.gemma else "sugoi" if args.translation else "ocr")
    bundle = next(b for b in model_catalog() if b.key == key)
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
