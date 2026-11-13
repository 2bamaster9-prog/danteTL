"""Native welcome/retry/progress fixture with synthetic bytes; never downloads real models."""

import argparse
import hashlib
import io
import json
import time
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import shiboken6
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from jp_overlay import model_store
from jp_overlay.hardware import Adapter, HardwareStatus
from jp_overlay.model_store import ModelBundle
from jp_overlay.models import ModelAsset
from jp_overlay.preferences import PreferenceStore
from jp_overlay.ui import MainWindow
from jp_overlay.windows import Windows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/first-run/welcome"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    state = args.output / uuid4().hex
    state.mkdir()
    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    data = b"fixture" * 1000000
    asset = ModelAsset("fixture", "1", "test.bin", hashlib.sha256(data).hexdigest(), len(data))
    models = tuple(
        ModelBundle(k, name, state / k, (asset,), "Synthetic verification bytes")
        for k, name in (("ocr", "MeikiOCR"), ("gemma", "Gemma"), ("sugoi", "Sugoi"))
    )
    hardware = Mock()
    hardware.snapshot.return_value = HardwareStatus(
        adapters=(Adapter("NVIDIA test adapter", 0x10DE, 16 * 2**30),), llama_device="cpu"
    )
    window = MainWindow(
        windows,
        Mock(),
        models=models,
        hardware=hardware,
        preferences_path=state / "preferences.json",
    )
    window.windows_combo.clear()
    window.show()
    window.offer_first_run()
    guide = window._setup_assistant
    assert guide
    stage, ticks = 0, 0
    failed = False
    evidence = {}
    started = time.monotonic()

    class Response(io.BytesIO):
        def read(self, size: int | None = -1):
            time.sleep(0.05)
            return super().read(min(size or -1, 256 * 1024))

    def screenshot(name: str) -> None:
        assert guide
        app.processEvents()  # Let layouts settle after changing the page/text.
        guide.grab().save(str(args.output / name))

    def tick():
        nonlocal stage, ticks, failed, guide
        ticks += 1
        try:
            assert guide
            assert time.monotonic() - started < 45
            if stage == 0:
                if guide.hardware_status is None:
                    return
                assert not guide.operation and not any(b.present() for b in models)
                screenshot("welcome.png")
                guide.next.click()
                screenshot("models.png")
                guide.next.click()
                assert guide.runtime.currentData().key == "nvidia"
                screenshot("acceleration.png")
                guide.runtime.setCurrentIndex(0)  # Explicit CPU avoids runtime/network install.
                guide.next.click()
                assert guide._plan and guide._plan.runtime is None
                screenshot("review.png")
                guide.next.click()
                stage = 1
            elif stage == 1:
                if not 0 < guide.progress_view.download.value() < 1000:
                    return
                assert guide.busy and guide.progress_view.download.isVisible()
                guide.grab().save(str(args.output / "progress.png"))
                evidence["two_bars_with_real_bytes"] = True
                guide.skip.click()
                stage = 2
            elif stage == 2:
                if guide.busy:
                    return
                assert "Retry" in guide.next.text()
                assert not list(state.rglob("*.tmp"))
                guide.next.click()
                stage = 3
            elif stage == 3:
                if guide.busy:
                    return
                assert guide._finished and models[0].present() and models[1].present()
                assert not models[2].present()
                guide.grab().save(str(args.output / "complete.png"))
                guide.next.click()
                stage = 4
            elif stage == 4:
                if not window._preferences.idle:
                    return
                assert PreferenceStore(state / "preferences.json").initial.setup_seen
                assert "Downloaded" in window._settings.models.download_badge.text()
                window.offer_first_run()
                assert not guide.isVisible()
                window._show_setup_assistant()
                guide = window._setup_assistant
                assert guide and guide.isVisible()
                guide.skip.click()
                window.close()
                stage = 5
            elif stage == 5:
                if window.isVisible():
                    return
                evidence.update(
                    explicit_downloads=True,
                    gpu_recommendation_cpu_override=True,
                    cancel_retry=True,
                    saved_completion=True,
                    reopen_from_settings=True,
                    clean_close=True,
                    responsive_ticks=ticks,
                )
                (args.output / "results.json").write_text(json.dumps(evidence, indent=2), "utf-8")
                print(json.dumps(evidence), flush=True)
                timer.stop()
                app.quit()
        except Exception:
            import traceback

            traceback.print_exc()
            failed = True
            timer.stop()
            window.close()
            app.quit()

    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(tick)
    timer.start()
    with patch.object(model_store, "urlopen", lambda *a, **kw: Response(data)):
        app.exec()
    shiboken6.delete(app)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
