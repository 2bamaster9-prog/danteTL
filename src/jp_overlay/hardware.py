"""Read Windows adapter identity without loading inference libraries or requiring WMI."""

import ctypes as ct
import sys
import threading
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Adapter:
    name: str
    vendor: int
    dedicated_bytes: int = 0


@dataclass(frozen=True, slots=True)
class HardwareStatus:
    adapters: tuple[Adapter, ...] = ()
    cuda_ocr: bool = False
    llama_device: str | None = None
    error: str = ""


class HardwareCheck:
    """One startup check; never load model/native inference libraries or install anything."""

    def __init__(self) -> None:
        self._done = threading.Event()
        self._result = HardwareStatus()
        self._thread = threading.Thread(target=self._run, name="hardware-check", daemon=True)

    def start(self) -> None:
        self._thread.start()

    @property
    def finished(self) -> bool:
        return self._done.is_set()

    def snapshot(self) -> HardwareStatus | None:
        return self._result if self.finished else None

    def _run(self) -> None:
        try:
            from jp_overlay.llama_runtime import installed_device
            from jp_overlay.ocr_runtime import gpu_runtime_installed

            self._result = HardwareStatus(
                detect_adapters(), gpu_runtime_installed(), installed_device()
            )
        except Exception as error:
            self._result = HardwareStatus(error=str(error))
        finally:
            self._done.set()


def recommended_profile(adapters: tuple[Adapter, ...]) -> str:
    # A discrete card normally has more dedicated memory than a CPU's integrated GPU.
    # This is a recommendation, not a driver/compute compatibility guarantee.
    supported = [a for a in adapters if a.vendor in (0x10DE, 0x1002)]
    if not supported:
        return "cpu"
    best = max(supported, key=lambda a: (a.dedicated_bytes, a.vendor == 0x10DE))
    return "nvidia" if best.vendor == 0x10DE else "amd"


class _Description(ct.Structure):
    _fields_ = [
        ("name", ct.c_wchar * 128),
        ("vendor", ct.c_uint32),
        ("device", ct.c_uint32),
        ("subsystem", ct.c_uint32),
        ("revision", ct.c_uint32),
        ("video", ct.c_size_t),
        ("system", ct.c_size_t),
        ("shared", ct.c_size_t),
        ("luid_low", ct.c_uint32),
        ("luid_high", ct.c_int32),
        ("flags", ct.c_uint32),
    ]


def _method(pointer: ct.c_void_p, index: int, *arguments: Any) -> Any:
    table = ct.cast(pointer, ct.POINTER(ct.POINTER(ct.c_void_p))).contents
    return ct.WINFUNCTYPE(ct.c_int32, ct.c_void_p, *arguments)(table[index])


def detect_adapters() -> tuple[Adapter, ...]:
    """Call on a worker. Fail visibly; the caller can still offer manual/CPU setup."""
    if sys.platform != "win32":
        return ()
    dxgi = ct.WinDLL("dxgi.dll")
    create = dxgi.CreateDXGIFactory1
    create.argtypes = (ct.c_void_p, ct.POINTER(ct.c_void_p))
    create.restype = ct.c_int32
    iid = (ct.c_ubyte * 16).from_buffer_copy(UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le)
    factory = ct.c_void_p()
    if create(iid, ct.byref(factory)) < 0:
        raise OSError("Windows could not enumerate graphics adapters. Choose a runtime manually.")
    found = []
    try:
        enum = _method(factory, 12, ct.c_uint32, ct.POINTER(ct.c_void_p))
        for index in range(32):
            adapter = ct.c_void_p()
            result = enum(factory, index, ct.byref(adapter))
            if result & 0xFFFFFFFF == 0x887A0002:  # DXGI_ERROR_NOT_FOUND
                break
            if result < 0:
                raise OSError("Windows adapter enumeration failed. Choose a runtime manually.")
            try:
                desc = _Description()
                if _method(adapter, 10, ct.POINTER(_Description))(adapter, ct.byref(desc)) < 0:
                    continue
                if not desc.flags & 2:  # Exclude the Microsoft software adapter.
                    found.append(Adapter(desc.name, desc.vendor, desc.video))
            finally:
                _method(adapter, 2)(adapter)
    finally:
        _method(factory, 2)(factory)
    return tuple(found)
