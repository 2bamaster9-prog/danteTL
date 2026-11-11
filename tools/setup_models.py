"""Explicit, resumable-by-file setup. This is the only model download entry point."""

import os
import tempfile
from pathlib import Path
from urllib.request import urlopen

from jp_overlay.models import ASSETS, model_directory, validate_asset


def main() -> None:
    directory = model_directory()
    directory.mkdir(parents=True, exist_ok=True)
    for asset in ASSETS:
        destination = directory / asset.filename
        try:
            validate_asset(destination, asset)
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
            validate_asset(temporary, asset)
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    print(f"OCR models verified in {directory}. Inference works offline.", flush=True)


if __name__ == "__main__":
    main()
