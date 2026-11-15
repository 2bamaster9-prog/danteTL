"""Exercise two real local assignments without capture, network or personal preferences."""

import argparse
import json
import socket
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from jp_overlay.domain import Rect
from jp_overlay.grouping import TextBlock
from jp_overlay.llama_runtime import installed_device, load_runtime
from jp_overlay.model_factories import translation_backends
from jp_overlay.tracking import TextTrack
from jp_overlay.translation import TranslationState
from jp_overlay.translation_plan import TranslationPlan
from jp_overlay.translation_routing import RoutedTranslationSession


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--short", default="gemma")
    parser.add_argument("--long", default="gemma-e4b")
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    choices = {c.preference_key: c for c in translation_backends()}
    selected = [choices[key] for key in (args.short, args.long)]
    assert all(not c.unavailable_reason for c in selected)
    assert installed_device() == args.device
    runtime = load_runtime(args.device)
    original_load = runtime.Llama

    def load(*args, **kwargs):
        kwargs["verbose"] = True
        return original_load(*args, **kwargs)

    if args.device == "cuda":
        assert all(c.key.endswith("-cuda") for c in selected), (
            "Strict GPU verification requires CUDA choices"
        )
    engines = []

    def factory(choice):
        engine = choice.create()
        engines.append(engine.cache_identity)
        return engine

    short = TextBlock((TextTrack(1, "会心率", Rect(10, 10, 120, 30)),))
    long = TextBlock(
        (
            TextTrack(
                2,
                "秘技を使用した後、次の戦闘開始時に攻撃力が35%アップする。",
                Rect(10, 80, 400, 30),
            ),
        ),
        dialogue=True,
    )
    started = time.monotonic()
    with (
        tempfile.TemporaryDirectory(dir=args.output) as folder,
        patch.object(runtime, "Llama", load),
        patch.object(socket.socket, "connect", side_effect=AssertionError("Unexpected network")),
    ):
        plan = TranslationPlan("local:" + args.short, "local:" + args.long)
        session = RoutedTranslationSession.assigned(
            plan,
            {"local:" + c.preference_key: lambda c=c: factory(c) for c in selected},
            Path(folder) / "cache",
        )
        session.start()
        try:
            session.update((short, long))
            while len(session.snapshot().results) != 2:
                snapshot = session.snapshot()
                assert snapshot.state != TranslationState.FAILED, snapshot.message
                assert time.monotonic() - started < 180, snapshot.message
                time.sleep(0.02)
            results = session.snapshot().results
            for _ in range(40):
                session.update((long, short))
                assert session.snapshot().results == results
            report = {
                "models": [c.name for c in selected],
                "device": args.device,
                "network_blocked": True,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "loads": len(engines),
                "results": [{"source": r.request.source, "english": r.english} for r in results],
                "stable_replays": 40,
            }
            assert len(engines) == len(plan.active_models)
            (args.output / "result.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), "utf-8"
            )
            print(json.dumps(report))
        finally:
            session.request_stop()
            deadline = time.monotonic() + 60
            while not session.finished:
                assert time.monotonic() < deadline, "Local owners did not drain"
                time.sleep(0.02)


if __name__ == "__main__":
    main()
