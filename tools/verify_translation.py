"""Offline Sugoi smoke check; original sample text only, no game data."""

import ctypes
import json
import socket
import time
from ctypes import wintypes
from unittest.mock import patch

from jp_overlay.sugoi import SugoiBackend, model_directory


def process_memory() -> dict[str, float]:
    """One Windows process snapshot, not a sustained memory-budget measurement."""

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak_working",
                "working",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "pagefile",
                "peak_pagefile",
                "private",
            )
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Counters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(
        kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        "working_set_mib": round(counters.working / 2**20, 1),
        "private_mib": round(counters.private / 2**20, 1),
        "peak_working_set_mib": round(counters.peak_working / 2**20, 1),
    }


def main() -> None:
    samples = ("新しい冒険が、ここから始まる。", "旅の準備はできましたか？", "設定")
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Unexpected network")):
        started = time.monotonic()
        backend = SugoiBackend(model_directory())
        load_ms = (time.monotonic() - started) * 1000
        try:
            started = time.monotonic()
            english = backend.translate(samples)
            duration = (time.monotonic() - started) * 1000
            assert len(english) == len(samples) and all(english)
            assert "adventure" in english[0].lower(), english
            assert any(word in english[2].lower() for word in ("setting", "config")), english
            print(
                json.dumps(
                    {
                        "network_blocked": True,
                        "backend": backend.cache_identity,
                        "load_ms": round(load_ms),
                        "batch_ms": round(duration),
                        "process_memory": process_memory(),
                        "samples": list(zip(samples, english, strict=True)),
                    },
                    ensure_ascii=True,
                    indent=2,
                )
            )
        finally:
            backend.close()


if __name__ == "__main__":
    main()
