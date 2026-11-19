"""Exercise two real local assignments without capture, network or personal preferences."""

import argparse
import json
import socket
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from dantejp.application.model_factories import translation_backends
from dantejp.domain import Rect
from dantejp.languages.target import ENGLISH
from dantejp.ocr.tracking import TextTrack
from dantejp.runtime.llama import installed_device, load_runtime
from dantejp.translation.grouping import TextBlock
from dantejp.translation.plan import TranslationPlan
from dantejp.translation.routing import RoutedTranslationSession
from dantejp.translation.worker import TranslationState


class CloudFixture:
    """Offline route replacement; native workers still run their real inference."""

    batch_size = 1

    def __init__(self, key):
        self.cache_identity = key

    def translate(self, texts, *, target=ENGLISH):
        return tuple("Fixture translation: " + text for text in texts)

    def close(self):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--short", default="gemma")
    parser.add_argument("--long", default="gemma-e4b")
    parser.add_argument("--device", choices=("cpu", "cuda", "vulkan"), required=True)
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

    if args.device != "cpu":
        assert all(c.key.endswith("-" + args.device) for c in selected), (
            "Strict GPU verification requires matching GPU choices"
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
        patch("diskcache.Cache", side_effect=AssertionError("Unsafe pickle cache enabled")),
        patch.object(
            original_load, "set_cache", side_effect=AssertionError("Upstream prompt cache enabled")
        ),
        patch.object(socket.socket, "connect", side_effect=AssertionError("Unexpected network")),
    ):
        plan = TranslationPlan("local:" + args.short, "local:" + args.long)
        factories = {"local:" + c.preference_key: lambda c=c: factory(c) for c in selected}
        session = RoutedTranslationSession(plan, factories, Path(folder) / "cache")
        session.start()
        try:

            def translate(label):
                deadline = time.monotonic() + 180
                while True:
                    session.update((label, long))
                    snapshot = session.snapshot()
                    assert snapshot.state != TranslationState.FAILED, snapshot.message
                    if len(snapshot.results) == 2:
                        return snapshot.results
                    assert time.monotonic() < deadline, snapshot.message
                    time.sleep(0.02)

            translate(short)
            results = session.snapshot().results
            for _ in range(40):
                session.update((long, short))
                assert session.snapshot().results == results
            # A changed cloud lane must not reload the still-selected native model.
            # Fresh labels require real inference, so stale cached results cannot pass.
            for index, source in enumerate(("攻撃力", "防御力")):
                remote = f"cloud:fixture-{index}"
                session.reconfigure(
                    TranslationPlan(plan.short, remote),
                    {**factories, remote: lambda remote=remote: CloudFixture(remote)},
                )
                label = TextBlock((TextTrack(10 + index, source, short.bounds),))
                switched = translate(label)
                assert any(r.request.source == source for r in switched)
                assert len(engines) == len(plan.active_models), "Unchanged native model reloaded"
            report = {
                "models": [c.name for c in selected],
                "device": args.device,
                "network_blocked": True,
                "upstream_disk_cache_disabled": True,
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "loads": len(engines),
                "results": [{"source": r.request.source, "english": r.english} for r in results],
                "stable_replays": 40,
                "cloud_switches_without_native_reload": 2,
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
