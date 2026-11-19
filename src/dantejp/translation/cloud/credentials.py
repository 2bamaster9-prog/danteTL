"""Windows Credential Manager boundary. Secrets never enter preferences or diagnostics."""

import ctypes
from ctypes import wintypes
from typing import Protocol

from dantejp.i18n import tr


class Secrets(Protocol):
    def read(self, key: str) -> str | None: ...
    def write(self, key: str, secret: str) -> None: ...
    def delete(self, key: str) -> None: ...


def valid_credential(value: object, *, limit: int = 16_384) -> bool:
    """Reject header controls/Unicode before an HTTP library can echo the value in an error."""
    return (
        isinstance(value, str)
        and 1 <= len(value) <= limit
        and all(33 <= ord(c) <= 126 for c in value)
    )


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsSecrets:
    def __init__(self, namespace: str = "DanteJP/cloud") -> None:
        self._namespace = namespace
        self._api = ctypes.WinDLL("advapi32", use_last_error=True)
        self._api.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_Credential)),
        ]
        self._api.CredReadW.restype = wintypes.BOOL
        self._api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        self._api.CredWriteW.restype = wintypes.BOOL
        self._api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._api.CredDeleteW.restype = wintypes.BOOL
        self._api.CredFree.argtypes = [ctypes.c_void_p]
        self._api.CredFree.restype = None

    def read(self, key: str) -> str | None:
        pointer = ctypes.POINTER(_Credential)()
        if not self._api.CredReadW(f"{self._namespace}/{key}", 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:
                return None
            raise OSError(tr("Windows could not read the saved API key."))
        try:
            credential = pointer.contents
            if credential.CredentialBlobSize > 2560:
                raise ValueError(tr("Saved API key exceeds the supported size."))
            value = ctypes.string_at(
                credential.CredentialBlob, credential.CredentialBlobSize
            ).decode("ascii")
            if not valid_credential(value, limit=2560):
                raise ValueError(tr("Saved API key is malformed. Replace it in Models."))
            return value
        except UnicodeError:
            raise ValueError(tr("Saved API key is malformed. Replace it in Models.")) from None
        finally:
            ctypes.memset(pointer.contents.CredentialBlob, 0, pointer.contents.CredentialBlobSize)
            self._api.CredFree(pointer)

    def write(self, key: str, secret: str) -> None:
        if not valid_credential(secret.strip(), limit=2560):
            raise ValueError(tr("Enter a valid API key without whitespace."))
        value = secret.strip().encode("ascii")
        blob = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        credential = _Credential()
        credential.Type, credential.Persist = 1, 2
        credential.TargetName = f"{self._namespace}/{key}"
        credential.UserName = "DanteJP"
        credential.CredentialBlobSize = len(value)
        credential.CredentialBlob = blob
        try:
            if not self._api.CredWriteW(ctypes.byref(credential), 0):
                raise OSError(tr("Windows could not save the API key."))
        finally:
            ctypes.memset(blob, 0, len(value))

    def delete(self, key: str) -> None:
        if (
            not self._api.CredDeleteW(f"{self._namespace}/{key}", 1, 0)
            and ctypes.get_last_error() != 1168
        ):
            raise OSError(tr("Windows could not remove the saved API key."))
