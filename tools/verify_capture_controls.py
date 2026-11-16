"""Record only our fixture's screen rectangle; verify border changes and clean OCR input."""

import argparse
import json
import os
import time
from pathlib import Path

import shiboken6
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from dantejp.capture.windows import Windows
from dantejp.capture.worker import CaptureSession
from dantejp.domain import CaptureState, WindowTarget, sample_box
from dantejp.ui.demo import DemoWindow
from dantejp.ui.inspection import frame_image
from dantejp.ui.overlay import OverlayWindow


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication([])
    demo = DemoWindow()
    demo.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
    demo.resize(700, 440)
    demo.show()
    demo.raise_()
    app.processEvents()
    target = WindowTarget(int(demo.winId()), os.getpid(), demo.windowTitle())
    session = CaptureSession(target, windows, fps=8)
    overlay = OverlayWindow(windows)
    evidence = {}

    def pump(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

    def wait_frame(after):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            value = session.snapshot()
            assert value.state != CaptureState.FAILED, value.message
            if value.frame and value.frame.sequence > after:
                return value.frame
            pump(0.05)
        raise AssertionError("No new frame")

    def screen_image():
        # Capture only the rectangle of our opaque, topmost fixture, never a monitor.
        rect = demo.frameGeometry()
        return (
            demo.screen().grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height()).toImage()
        )

    def client_image():
        origin = demo.mapToGlobal(QPoint(0, 0))
        return (
            demo.screen()
            .grabWindow(0, origin.x(), origin.y(), demo.width(), demo.height())
            .toImage()
        )

    def yellow_edge_pixels(image):
        # The fixture's corner marker is inside the client, not this outer 4px rim.
        return sum(
            1
            for y in range(image.height())
            for x in range(image.width())
            if min(x, y, image.width() - x - 1, image.height() - y - 1) < 4
            and (c := image.pixelColor(x, y)).red() > 150
            and c.green() > 130
            and c.blue() < 100
        )

    try:
        session.start()
        first = wait_frame(0)
        overlay.align(first.geometry.client)
        pump(0.5)
        before = screen_image()
        before.save(str(args.output / "border-on.png"))
        current = session.snapshot().frame
        assert current is not None
        sequence = current.sequence
        session.set_border(False)
        assert session.snapshot().frame is not None
        pump(0.8)
        after = wait_frame(sequence)
        assert after.sequence > sequence
        without = screen_image()
        without.save(str(args.output / "border-off.png"))
        box = sample_box(after.width, after.height)
        raw = frame_image(after)
        assert raw.pixelColor(box.x + 5, box.y + 5).name() == "#29465e"
        # Screen composition includes the translucent overlay at the same client pixel.
        client = client_image()
        assert client.width() == after.width and client.height() == after.height
        assert client.pixelColor(box.x + 5, box.y + 5).name() != "#29465e"
        client.save(str(args.output / "screen-with-overlay.png"))
        raw.save(str(args.output / "raw-without-overlay.png"))
        evidence.update(
            recording_contains_overlay=True,
            raw_window_capture_excludes_overlay=True,
            native_affinity=windows.overlay_properties(int(overlay.winId()))[1],
            sequence_before=sequence,
            sequence_after=after.sequence,
            yellow_pixels_before=yellow_edge_pixels(before),
            yellow_pixels_after=yellow_edge_pixels(without),
        )
        hwnd = int(overlay.winId())
        for included in (False, True, False, True):
            overlay.set_capture_included(included)
            pump(0.2)
            assert windows.overlay_properties(hwnd)[1] == (0 if included else 0x11)
            assert overlay.isVisible() and int(overlay.winId()) == hwnd
            recorded = client_image()
            assert (recorded.pixelColor(box.x + 5, box.y + 5).name() != "#29465e") == included
            recorded.save(str(args.output / f"recording-included-{included}.png"))
            current = wait_frame(after.sequence)
            assert frame_image(current).pixelColor(box.x + 5, box.y + 5).name() == "#29465e"
        evidence["recording_toggle_live_without_replacing_overlay_or_capture"] = True
        evidence["exclusion_keeps_clean_game_pixels_in_recording"] = True
        session.set_border(True)
        pump(0.8)
        restored = wait_frame(after.sequence)
        shown = screen_image()
        shown.save(str(args.output / "border-restored.png"))
        evidence["yellow_pixels_restored"] = yellow_edge_pixels(shown)
        evidence["sequence_restored"] = restored.sequence
        evidence["border_visibly_disabled"] = (
            evidence["yellow_pixels_before"] > evidence["yellow_pixels_after"] + 100
            and evidence["yellow_pixels_restored"] > evidence["yellow_pixels_after"] + 100
        )
        assert evidence["native_affinity"] == 0
        assert evidence["border_visibly_disabled"], evidence
    finally:
        session.request_stop()
        deadline = time.monotonic() + 10
        while not session.finished and time.monotonic() < deadline:
            pump(0.05)
        assert session.finished, "Capture did not drain"
        overlay.close()
        demo.close()
        shiboken6.delete(overlay)
        shiboken6.delete(demo)
        shiboken6.delete(app)
    (args.output / "result.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
