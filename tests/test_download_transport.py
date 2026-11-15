"""Actual installer/HTTP cancellation replays; no remote servers or model files."""

import hashlib
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from jp_overlay import download_transport, model_store, runtime_downloads
from jp_overlay.models import ModelAsset
from jp_overlay.setup_values import Cancelled


@contextmanager
def server(phase: str, data: bytes = b"good"):
    entered, stop, disconnected = threading.Event(), threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            try:
                if phase == "complete":
                    self.send_response(200)
                    self.end_headers()  # Exercise unknown Content-Length as well.
                    self.wfile.write(data)
                    return
                if phase == "headers":
                    self.wfile.write(b"HTTP/1.1 200 OK\r\nX-Trickle: ")
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", "1000000")
                    self.end_headers()
                entered.set()
                while not stop.wait(0.02):
                    self.wfile.write(b"x")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                disconnected.set()

    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, kwargs={"poll_interval": 0.02})
    thread.start()
    try:
        yield f"http://127.0.0.1:{http.server_port}/asset", entered, disconnected
    finally:
        stop.set()
        http.shutdown()
        http.server_close()
        thread.join(2)
        assert not thread.is_alive()


def installer(kind, root, url, monkeypatch, data=b"good", size=1000000):
    digest = hashlib.sha256(data).hexdigest()
    if kind == "model":
        monkeypatch.setattr(ModelAsset, "url", property(lambda _: url))
        asset = ModelAsset("fixture", "revision", "weights", digest, size)
        bundle = model_store.ModelBundle("fixture", "Fixture", root, (asset,), "")
        destination = root / "weights"

        def run(progress, cancel):
            model_store.install_model(bundle, progress, cancel)
    else:
        wheel = runtime_downloads.RuntimeArtifact("fixture", "fixture.whl", url, digest, size)
        destination = root / digest / "fixture.whl"

        def run(progress, cancel):
            runtime_downloads.download_artifact(wheel, root, progress, cancel)

    destination.parent.mkdir(parents=True, exist_ok=True)
    return run, destination


@pytest.mark.parametrize("kind", ["model", "runtime"])
@pytest.mark.parametrize("phase", ["headers", "body"])
@pytest.mark.parametrize("interrupt", ["cancel", "deadline"])
def test_trickling_download_stops_before_peer_finishes_and_cleans_partial(
    tmp_path, monkeypatch, kind, phase, interrupt
):
    monkeypatch.setattr(
        download_transport, "DOWNLOAD_TIMEOUT", 1.5 if interrupt == "deadline" else 30
    )
    with server(phase) as (url, entered, disconnected):
        run, destination = installer(kind, tmp_path, url, monkeypatch)
        destination.write_bytes(b"previous")
        cancel, done = threading.Event(), threading.Event()
        errors = []

        def work():
            try:
                run(lambda _: None, cancel)
            except Exception as error:
                errors.append(error)
            finally:
                done.set()

        thread = threading.Thread(target=work)
        thread.start()
        try:
            assert entered.wait(3), "The actual HTTP request must reach the controlled wait"
            started = time.monotonic()
            if interrupt == "cancel":
                cancel.set()
            assert done.wait(3), "Cancellation/deadline must not wait for the peer to close"
            assert time.monotonic() - started < 3
            assert len(errors) == 1
            assert isinstance(errors[0], Cancelled if interrupt == "cancel" else RuntimeError)
            if interrupt == "deadline":
                assert "timed out" in str(errors[0])
            assert disconnected.wait(2), "The child must release its network connection"
            assert destination.read_bytes() == b"previous"
            assert not list(tmp_path.rglob("*.part"))
        finally:
            cancel.set()
            thread.join(3)
            assert not thread.is_alive()


@pytest.mark.parametrize("kind", ["model", "runtime"])
def test_real_transfer_verifies_publishes_and_reports_exact_bytes(tmp_path, monkeypatch, kind):
    data = b"verified bytes" * 30000
    with server("complete", data) as (url, _, _):
        run, destination = installer(kind, tmp_path, url, monkeypatch, data, len(data))
        progress = []
        run(progress.append, threading.Event())
        assert destination.read_bytes() == data
        assert any(p.download and p.download.received == len(data) for p in progress)
        assert not list(tmp_path.rglob("*.part"))


@pytest.mark.parametrize("phase", ["dns", "connect"])
def test_cancel_interrupts_blocked_connection_setup(tmp_path, monkeypatch, phase):
    # Patch only the disposable child's socket, before real urllib connection setup.
    # Blocking name resolution cannot be killed by an asyncio/socket inactivity timeout.
    marker = tmp_path / "entered"
    original = download_transport.module_command

    def command(python, module, *args):
        script = (
            "import socket,time; from pathlib import Path; "
            "from jp_overlay.download_transport import _receive; "
            f"marker=Path({str(marker)!r}); "
            "blocked=lambda *a,**kw: (marker.write_text('entered'),time.sleep(30))[1]; "
            + (
                "socket.getaddrinfo=blocked; "
                if phase == "dns"
                else "socket.socket.connect=blocked; "
            )
            + f"_receive({args[0]!r},Path({args[1]!r}),{args[2]})"
        )
        return [str(python), "-c", script]

    monkeypatch.setattr(download_transport, "module_command", command)
    cancel = threading.Event()
    done = threading.Event()
    errors = []

    def work():
        try:
            download_transport.download_file(
                "http://127.0.0.1:1/file", tmp_path / "a.part", 10, lambda *_: None, cancel
            )
        except Exception as error:
            errors.append(error)
        finally:
            done.set()

    worker = threading.Thread(target=work)
    worker.start()
    try:
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            assert not done.wait(0.01)
        assert marker.exists()
        cancel.set()
        assert done.wait(2)
        assert len(errors) == 1 and isinstance(errors[0], Cancelled)
    finally:
        cancel.set()
        worker.join(3)
        monkeypatch.setattr(download_transport, "module_command", original)
        assert not worker.is_alive()


def test_windowed_helper_keeps_progress_pipe(tmp_path, monkeypatch):
    import sys

    monkeypatch.setattr(
        download_transport.sys, "executable", str(Path(sys.executable).with_name("pythonw.exe"))
    )
    with server("complete") as (url, _, _):
        progress = []
        destination = tmp_path / "windowed.part"
        download_transport.download_file(
            url, destination, 4, lambda *p: progress.append(p), threading.Event()
        )
        assert destination.read_bytes() == b"good"
        assert progress[-1] == (4, 0)
