"""Explicit, resumable-by-file setup. This is the only model download entry point."""

import argparse
import os
import tempfile
from pathlib import Path
from urllib.request import urlopen

from jp_overlay.models import ASSETS, model_directory, validate_asset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--translation", action="store_true", help="Install Sugoi V4 instead of OCR"
    )
    parser.add_argument("--gemma", action="store_true", help="Install optional Gemma 4 E2B QAT")
    args = parser.parse_args()
    assets, directory, setup = ASSETS, model_directory(), "Setup OCR.cmd"
    if args.gemma and args.translation:
        parser.error("Choose either --gemma or --translation.")
    if args.gemma:
        from jp_overlay.gemma import ASSETS as gemma_assets
        from jp_overlay.gemma import model_directory as gemma_directory

        assets, directory, setup = gemma_assets, gemma_directory(), "Setup Gemma.cmd"
    if args.translation:
        from jp_overlay.sugoi import ASSETS as sugoi_assets
        from jp_overlay.sugoi import model_directory as sugoi_directory

        assets, directory, setup = sugoi_assets, sugoi_directory(), "Setup Translation.cmd"
    directory.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        destination = directory / asset.filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            validate_asset(destination, asset, setup)
        except RuntimeError:
            pass
        else:
            print(f"Verified: {asset.filename}", flush=True)
            continue
        print(f"Downloading {asset.filename} ({asset.size / 1_000_000:.1f} MB)…", flush=True)
        # A unique temporary file prevents interrupted/concurrent setup corrupting a model.
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, suffix=".part", delete=False) as output:
                temporary = Path(output.name)
                with urlopen(asset.url, timeout=60) as response:
                    received = 0
                    while chunk := response.read(1024 * 1024):
                        received += len(chunk)
                        if received > asset.size:
                            raise RuntimeError("Download exceeded the pinned model size.")
                        output.write(chunk)
            validate_asset(temporary, asset, setup)
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    print(f"Models verified in {directory}. Inference works offline.", flush=True)


if __name__ == "__main__":
    main()
