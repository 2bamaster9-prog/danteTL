"""In-memory transport substitute for installer policy tests (no network/child process)."""

from dantetl.runtime.setup_values import Cancelled


def download_bytes(data: bytes):
    def download(url, destination, limit, progress, cancel):
        with destination.open("wb") as output:
            for offset in range(0, len(data), 256 * 1024):
                if cancel.is_set():
                    raise Cancelled()
                chunk = data[offset : offset + 256 * 1024]
                if limit and offset + len(chunk) > limit:
                    raise RuntimeError("Download exceeded its size limit.")
                output.write(chunk)
                progress(offset + len(chunk), 0)

    return download
