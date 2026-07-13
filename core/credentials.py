from __future__ import annotations

import ctypes
import hashlib
import os
from ctypes import wintypes
from urllib.parse import urlsplit, urlunsplit


SERVICE_NAME = "BossLocalCapture"


def normalize_api_base(value: str) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("API Base 必须是有效的 http:// 或 https:// 地址")
    if parsed.username or parsed.password:
        raise ValueError("API Base 不得包含用户名或密码")
    host = parsed.hostname.lower()
    if parsed.port:
        host = f"{host}:{parsed.port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), host, path, "", ""))


def credential_reference(provider: str, api_base: str) -> str:
    account = f"{str(provider or '').strip().lower()}|{normalize_api_base(api_base)}"
    digest = hashlib.sha256(account.encode("utf-8")).hexdigest()[:24]
    return f"{SERVICE_NAME}/{digest}"


class MemoryCredentialBackend:
    def __init__(self) -> None:
        self.values: dict[str, tuple[str, str]] = {}

    def write(self, target: str, username: str, secret: str) -> None:
        self.values[target] = (username, secret)

    def read(self, target: str) -> str:
        return self.values.get(target, ("", ""))[1]

    def delete(self, target: str) -> bool:
        return self.values.pop(target, None) is not None


class WindowsCredentialBackend:
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    class CREDENTIALW(ctypes.Structure):
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

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows Credential Manager is only available on Windows")
        self._advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._advapi32.CredWriteW.argtypes = [ctypes.POINTER(self.CREDENTIALW), wintypes.DWORD]
        self._advapi32.CredWriteW.restype = wintypes.BOOL
        self._advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(self.CREDENTIALW)),
        ]
        self._advapi32.CredReadW.restype = wintypes.BOOL
        self._advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._advapi32.CredDeleteW.restype = wintypes.BOOL
        self._advapi32.CredFree.argtypes = [ctypes.c_void_p]

    def write(self, target: str, username: str, secret: str) -> None:
        blob = secret.encode("utf-16-le")
        buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        credential = self.CREDENTIALW()
        credential.Type = self.CRED_TYPE_GENERIC
        credential.TargetName = target
        credential.CredentialBlobSize = len(blob)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        credential.UserName = username
        if not self._advapi32.CredWriteW(ctypes.byref(credential), 0):
            raise ctypes.WinError(ctypes.get_last_error())

    def read(self, target: str) -> str:
        pointer = ctypes.POINTER(self.CREDENTIALW)()
        if not self._advapi32.CredReadW(target, self.CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            error = ctypes.get_last_error()
            if error == self.ERROR_NOT_FOUND:
                return ""
            raise ctypes.WinError(error)
        try:
            credential = pointer.contents
            blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            return blob.decode("utf-16-le")
        finally:
            self._advapi32.CredFree(pointer)

    def delete(self, target: str) -> bool:
        if self._advapi32.CredDeleteW(target, self.CRED_TYPE_GENERIC, 0):
            return True
        error = ctypes.get_last_error()
        if error == self.ERROR_NOT_FOUND:
            return False
        raise ctypes.WinError(error)


class CredentialStore:
    def __init__(self, backend=None) -> None:
        self.backend = backend or WindowsCredentialBackend()

    def save(self, provider: str, api_base: str, secret: str) -> str:
        value = str(secret or "").strip()
        if not value:
            raise ValueError("API Key 不能为空")
        reference = credential_reference(provider, api_base)
        account = f"{str(provider or '').strip().lower()}|{normalize_api_base(api_base)}"
        self.backend.write(reference, account, value)
        return reference

    def read(self, provider: str, api_base: str) -> str:
        return self.backend.read(credential_reference(provider, api_base))

    def delete(self, provider: str, api_base: str) -> bool:
        return self.backend.delete(credential_reference(provider, api_base))

    def resolve(self, provider: str, api_base: str, explicit: str, env_name: str) -> str:
        if str(explicit or "").strip():
            return str(explicit).strip()
        saved = self.read(provider, api_base)
        if saved:
            return saved
        return os.getenv(str(env_name or "").strip(), "").strip()
