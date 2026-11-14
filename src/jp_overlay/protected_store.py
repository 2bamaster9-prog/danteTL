"""Atomic user-bound DPAPI records and interprocess locks for rotating OAuth tokens."""

import ctypes
import json
import msvcrt
import os
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from uuid import uuid4


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _protect(data: bytes, *, decrypt: bool = False) -> bytes:
    raw = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, output = _Blob(len(data), raw), _Blob()
    api = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    call = api.CryptUnprotectData if decrypt else api.CryptProtectData
    call.argtypes = [
        ctypes.POINTER(_Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_Blob),
    ]
    call.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    try:
        if not call(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
            raise OSError("Windows could not unlock/save this ChatGPT connection.")
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.memset(raw, 0, len(data))
        if output.data:
            if decrypt:
                ctypes.memset(output.data, 0, output.size)
            kernel.LocalFree(output.data)


class ProtectedStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, key: str) -> Path:
        if not re.fullmatch(r"(?:account-[0-9a-f]{32}|host)", key):
            raise ValueError("Invalid protected record ID.")
        return self.directory / (key + ".dat")

    def read(self, key: str) -> dict:
        path = self._path(key)
        if not path.exists():
            return {}
        if path.stat().st_size > 131_072:
            raise ValueError("ChatGPT connection record is too large.")
        value = json.loads(_protect(path.read_bytes(), decrypt=True))
        if not isinstance(value, dict):
            raise ValueError("Invalid ChatGPT connection record.")
        if "_protected_record" in value:
            if (
                value.get("_protected_record") != 1
                or value.get("key") != key
                or not isinstance(value.get("value"), dict)
            ):
                raise ValueError("ChatGPT connection record does not match this account.")
            return value["value"]
        # Existing encrypted records are upgraded on their next successful write.
        return value

    def write(self, key: str, value: dict) -> None:
        path = self._path(key)
        data = json.dumps(
            {"_protected_record": 1, "key": key, "value": value}, ensure_ascii=False
        ).encode("utf-8")
        if len(data) > 100_000:
            raise ValueError("ChatGPT connection record exceeds its size limit.")
        encrypted = _protect(data)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(encrypted)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def account_keys(self) -> tuple[str, ...]:
        return tuple(sorted(p.stem for p in self.directory.glob("account-*.dat")))[:8]

    @contextmanager
    def lock(self, key: str, *, check: Callable[[], None] | None = None) -> Iterator[None]:
        path = self._path(key).with_suffix(".lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as stream:
            if not path.stat().st_size:
                stream.write(b"0")
                stream.flush()
            deadline = time.monotonic() + 20
            while True:
                if check:
                    check()
                stream.seek(0)
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise OSError(
                            "Another DanteJP instance is updating this ChatGPT account."
                        ) from None
                    time.sleep(0.05)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
