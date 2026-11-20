import pytest

from dantetl.domain import (
    CapturedFrame,
    CaptureSnapshot,
    CaptureState,
    Rect,
    WindowGeometry,
    client_crop,
    overlay_ready,
)


def geometry(x: int = 100, dpi: int = 96) -> WindowGeometry:
    return WindowGeometry(
        Rect(x + 8, 130, 800, 600),
        Rect(x + 1, 101, 814, 637),
        Rect(x, 100, 816, 638),
        dpi,
    )


@pytest.mark.parametrize("x,dpi", [(100, 96), (-1920, 144), (3840, 192)])
def test_visible_window_crop_preserves_physical_client_offset(x: int, dpi: int) -> None:
    assert client_crop((814, 637), geometry(x, dpi)) == Rect(7, 29, 800, 600)


def test_full_window_and_client_only_frames() -> None:
    assert client_crop((816, 638), geometry()) == Rect(8, 30, 800, 600)
    assert client_crop((800, 600), geometry()) == Rect(0, 0, 800, 600)


def test_old_size_frame_during_resize_is_rejected() -> None:
    assert client_crop((1280, 720), geometry()) is None


def test_borderless_capture_has_no_offset() -> None:
    bounds = Rect(-2560, 0, 2560, 1440)
    assert client_crop(bounds.size, WindowGeometry(bounds, bounds, bounds, 144)) == Rect(
        0, 0, 2560, 1440
    )


def test_minimized_window_is_not_a_usable_crop() -> None:
    bounds = Rect(0, 0, 800, 600)
    assert client_crop(bounds.size, WindowGeometry(bounds, bounds, bounds, 96, True)) is None


@pytest.mark.parametrize(
    "state", [CaptureState.STARTING, CaptureState.STOPPING, CaptureState.FAILED]
)
def test_overlay_requires_running_capture(state: CaptureState) -> None:
    current = geometry()
    frame = CapturedFrame(1, 0, current, b"")
    assert not overlay_ready(CaptureSnapshot(state, frame), current, True)


def test_overlay_follows_movement_but_hides_for_resize_focus_loss_and_closure() -> None:
    current = geometry()
    snapshot = CaptureSnapshot(CaptureState.RUNNING, CapturedFrame(1, 0, current, b""))
    assert overlay_ready(snapshot, geometry(x=500), True)
    assert not overlay_ready(snapshot, current, False)
    assert not overlay_ready(snapshot, None, True)
    resized = WindowGeometry(
        Rect(0, 0, 1000, 700), current.visible_bounds, current.window_bounds, 96
    )
    assert not overlay_ready(snapshot, resized, True)
