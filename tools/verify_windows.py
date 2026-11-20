"""Exercise real capture against our own fixture on an interactive Windows desktop.

No screenshots of other apps are collected. Output contains dimensions and assertion results.
The fixture and overlay are closed after the session's native worker finishes.
"""

import json
import os
import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from dantetl.capture.windows import Windows
from dantetl.capture.worker import CaptureSession
from dantetl.domain import CaptureState, WindowTarget, overlay_ready, sample_box
from dantetl.ui.demo import DemoWindow
from dantetl.ui.inspection import frame_image
from dantetl.ui.overlay import OverlayWindow


def main() -> int:
    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    demo = DemoWindow()
    demo.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    demo.show()
    target = WindowTarget(int(demo.winId()), os.getpid(), demo.windowTitle())
    overlay = OverlayWindow(windows)
    session = CaptureSession(target, windows)
    session.start()
    started = time.monotonic()
    stage = 0
    sequence = 0
    failure = ""
    target_closed = False
    evidence: dict[str, object] = {}

    def tick() -> None:
        nonlocal stage, sequence, failure, session, target_closed
        try:
            if time.monotonic() - started > 30:
                failure = "Native verification exceeded its shutdown deadline"
                session.request_stop()
                overlay.close()
                if not target_closed:
                    demo.close()
                timer.stop()
                app.exit(1)
                return
            if stage == 99:
                if session.finished:
                    timer.stop()
                    overlay.close()
                    if not target_closed:
                        demo.close()
                    app.quit()
                return
            if stage == 5:
                if session.finished:
                    evidence["first_shutdown_finished"] = True
                    demo.showNormal()
                    session = CaptureSession(target, windows)
                    session.start()
                    sequence = 0
                    stage = 6
                return
            if stage == 7:
                if session.finished:
                    assert session.snapshot().state != CaptureState.FAILED
                    evidence["source_closure_finished"] = True
                    evidence["elapsed_seconds"] = round(time.monotonic() - started, 2)
                    stage = 99
                return
            snapshot = session.snapshot()
            if snapshot.state == CaptureState.FAILED:
                raise RuntimeError(snapshot.message)
            if time.monotonic() - started > 20:
                raise RuntimeError(f"Timed out at stage {stage}: {snapshot.state}")
            frame = snapshot.frame
            if frame is None or frame.sequence == sequence:
                return
            geometry = windows.geometry(target)
            if frame.geometry.client.size != geometry.client.size:
                return
            sequence = frame.sequence
            image = frame_image(frame)
            # Markers sit in the client corners, beyond title bars and resize borders.
            assert image.pixelColor(8, 8).name() == "#ff00ff", "Top-left crop is misaligned"
            assert image.pixelColor(frame.width - 8, frame.height - 8).name() == "#ffff00", (
                "Bottom-right crop is misaligned"
            )
            if stage == 0:
                foreground_before = windows.is_foreground(target)
                overlay.align(geometry.client)
                assert windows.is_foreground(target) == foreground_before, "Overlay stole focus"
                style, affinity = windows.overlay_properties(int(overlay.winId()))
                assert style & 0x80000 and style & 0x20 and style & 0x08000000
                assert affinity == 0, "Overlay must allow screenshots/display recording"
                evidence["initial_client"] = geometry.client.size
                evidence["dpi"] = geometry.dpi
                evidence["native_input_transparency"] = True
                stage = 1
            elif stage == 1:
                overlay_target = WindowTarget(int(overlay.winId()), os.getpid(), "overlay")
                assert windows.geometry(overlay_target).client == geometry.client, (
                    "Overlay bounds differ"
                )
                box = sample_box(frame.width, frame.height)
                assert image.pixelColor(box.x + 5, box.y + 5).name() == "#29465e", (
                    "Overlay contaminated source capture"
                )
                evidence["source_excludes_overlay"] = True
                demo.move(demo.x() + 35, demo.y() + 30)
                demo.resize(760, 500)
                stage = 2
            elif stage == 2:
                if geometry.client.size == evidence["initial_client"]:
                    return
                overlay.align(geometry.client)
                evidence["resized_client"] = geometry.client.size
                stage = 3
            elif stage == 3:
                overlay_target = WindowTarget(int(overlay.winId()), os.getpid(), "overlay")
                assert windows.geometry(overlay_target).client == geometry.client, (
                    "Resize alignment failed"
                )
                assert not overlay_ready(snapshot, geometry, False), "Focus loss must hide overlay"
                demo.showMinimized()
                overlay.hide()
                stage = 4
                QTimer.singleShot(300, finish_minimized)
            elif stage == 6:
                evidence["restart_received_frame"] = True
                demo.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
                demo.close()
                target_closed = True
                stage = 7
        except Exception as error:
            failure = str(error)
            print(f"FAIL: {failure}", flush=True)
            session.request_stop()
            stage = 99

    def finish_minimized() -> None:
        nonlocal stage, failure
        try:
            assert windows.geometry(target).minimized
            assert not overlay_ready(session.snapshot(), windows.geometry(target), True)
            evidence["minimize_and_focus_policy"] = True
            evidence["frames_received"] = sequence
        except Exception as error:
            failure = str(error)
        finally:
            session.request_stop()
            stage = 99 if failure else 5

    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(tick)
    timer.start()
    app.exec()
    evidence["shutdown_finished"] = session.finished
    print(json.dumps(evidence, indent=2))
    return 1 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
