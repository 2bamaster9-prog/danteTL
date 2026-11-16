"""Offline translation smoke/comparison check; original sample text, no game captures."""

import argparse
import ctypes
import json
import socket
import subprocess
import time
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch

from dantejp.translation.backend import ContextualBackend
from dantejp.translation.worker import TranslationBackend


def process_memory(pid: int | None = None) -> dict[str, float]:
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
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Counters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    handle = kernel.GetCurrentProcess() if pid is None else kernel.OpenProcess(0x410, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if pid is not None:
            kernel.CloseHandle(handle)
    return {
        "working_set_mib": round(counters.working / 2**20, 1),
        "private_mib": round(counters.private / 2**20, 1),
        "peak_working_set_mib": round(counters.peak_working / 2**20, 1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        choices=("gemma", "gemma-e4b", "qwen35-4b", "plamo-2b", "plamo-0.8b"),
        default="gemma",
    )
    parser.add_argument(
        "--device", choices=("cpu", "cuda", "vulkan"), help="Require this language-model engine"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    samples = (
        "新しい冒険が、ここから始まる。",
        "旅の準備はできましたか？",
        "設定",
        "ストーリーを振り返る",
        "装備を強化する",
        "残り時間：３０秒",
        "まさか、こんなところで君に会うとは思わなかった。無事でよかったよ。",
        "先に行って。ここは私が何とかするから。",
        "敵全体にダメージを与え、攻撃力を上げる。",
    )

    def gpu_memory() -> str:
        try:
            return subprocess.check_output(
                ["nvidia-smi", "--query-gpu=name,memory.used", "--format=csv,noheader"],
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).strip()
        except (OSError, subprocess.SubprocessError):
            return "unavailable"

    gpu_before = gpu_memory()
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Unexpected network")):
        started = time.monotonic()
        backend: TranslationBackend
        from dantejp.application.model_factories import create_curated_translator
        from dantejp.runtime.llama import installed_device
        from dantejp.translation.backends.gemma import GemmaBackend
        from dantejp.translation.backends.gemma import model_directory as gemma_directory

        device = installed_device()
        assert device is not None, "Language-model engine is missing"
        assert not args.device or device == args.device, "Unexpected engine; no silent fallback"
        backend = (
            GemmaBackend(gemma_directory(), device=device)
            if args.backend == "gemma"
            else create_curated_translator(args.backend)
        )
        load_ms = (time.monotonic() - started) * 1000
        try:
            answers, timings = [], []
            for source in samples:
                started = time.monotonic()
                answers.append(backend.translate((source,))[0])
                timings.append(round((time.monotonic() - started) * 1000, 1))
            english = tuple(answers)
            started = time.monotonic()
            repeated = backend.translate((samples[0],))[0]
            repeat_ms = (time.monotonic() - started) * 1000
            assert len(english) == len(samples) and all(english)
            assert "adventure" in english[0].lower(), english
            assert any(word in english[2].lower() for word in ("setting", "config")), english
            dialogue = []
            if isinstance(backend, ContextualBackend):
                from dantejp.translation.dialogue.context import DialogueTurn

                context = (
                    DialogueTurn("私はリナ。これからよろしくね。", "I'm Rina. Nice to meet you."),
                )
                source = "リナが待っている。先に行こう。"
                for history in ((), context):
                    started = time.monotonic()
                    answer = backend.translate_with_context(source, history)
                    dialogue.append(
                        {
                            "context_turns": len(history),
                            "english": answer,
                            "ms": round((time.monotonic() - started) * 1000, 1),
                        }
                    )
                assert "Rina" in dialogue[-1]["english"], dialogue
            report = json.dumps(
                {
                    "network_blocked": True,
                    "backend": backend.cache_identity,
                    "load_ms": round(load_ms),
                    "source_ms": timings,
                    "repeat_ms": round(repeat_ms, 1),
                    "repeat_answer": repeated,
                    "gpu_total_before": gpu_before,
                    "gpu_total_loaded": gpu_memory(),
                    "process_memory": process_memory(),
                    "samples": list(zip(samples, english, strict=True)),
                    "dialogue_context": dialogue,
                },
                ensure_ascii=True,
                indent=2,
            )
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(report, encoding="utf-8")
            print(report)
        finally:
            backend.close()


if __name__ == "__main__":
    main()
