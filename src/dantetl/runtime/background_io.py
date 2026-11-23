"""Let foreground applications take precedence over bulk setup I/O on Windows."""

import ctypes
import sys
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def background_io() -> Iterator[None]:
    if sys.platform != "win32":
        yield
        return
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentThread.restype = ctypes.c_void_p
    kernel.SetThreadPriority.argtypes = (ctypes.c_void_p, ctypes.c_int)
    thread = kernel.GetCurrentThread()
    entered = kernel.SetThreadPriority(thread, 0x10000)  # THREAD_MODE_BACKGROUND_BEGIN
    try:
        yield
    finally:
        if entered:
            kernel.SetThreadPriority(thread, 0x20000)  # THREAD_MODE_BACKGROUND_END
