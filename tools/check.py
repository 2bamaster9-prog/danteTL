"""Fast development checks; no windows, network requests, or model downloads."""

import subprocess
import sys


def main() -> int:
    checks = [
        ["ruff", "format", "--check", "."],
        ["ruff", "check", "."],
        ["pyright"],
        ["pytest", "-q", "-m", "not windows"],
    ]
    for check in checks:
        print(f"Running {' '.join(check)}", flush=True)
        result = subprocess.run([sys.executable, "-m", *check], check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
