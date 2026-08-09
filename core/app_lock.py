from __future__ import annotations

import hashlib
import ctypes
import json
import os
import threading
from pathlib import Path
from typing import BinaryIO


class ApplicationLockError(RuntimeError):
    pass


_HELD_IDENTITIES: set[str] = set()
_HELD_IDENTITIES_LOCK = threading.Lock()


class DatabaseApplicationLock:
    def __init__(self, database_path: Path, *, lock_root: Path | None = None) -> None:
        self.database_path = database_path.resolve()
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        root = lock_root or local / "RecruitingTalentWorkbench" / "locks"
        identity = hashlib.sha256(os.path.normcase(str(self.database_path)).encode("utf-8")).hexdigest()
        self.identity = identity
        self.lock_path = root / f"{identity}.lock"
        self._handle: BinaryIO | None = None
        self._mutex_handle: int | None = None

    def acquire(self) -> None:
        if self._handle is not None or self._mutex_handle is not None:
            return
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            self._acquire_windows_mutex()
            self.lock_path.write_text(
                json.dumps({"pid": os.getpid(), "database": str(self.database_path)}),
                encoding="utf-8",
            )
            return
        handle = self.lock_path.open("a+b")
        if self.lock_path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        try:
            self._lock_file(handle)
        except OSError as exc:
            handle.close()
            raise ApplicationLockError(
                "当前数据库正在被其他实例使用。请先关闭另一个实例。\n"
                f"数据库路径：{self.database_path}"
            ) from exc
        handle.seek(1)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "database": str(self.database_path)}).encode("utf-8"))
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        if self._mutex_handle is not None:
            self._close_windows_handle(self._mutex_handle)
            self._mutex_handle = None
            with _HELD_IDENTITIES_LOCK:
                _HELD_IDENTITIES.discard(self.identity)
            return
        if self._handle is None:
            return
        try:
            self._unlock_file(self._handle)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "DatabaseApplicationLock":
        self.acquire()
        return self

    def __exit__(self, *_args) -> None:
        self.release()

    def _acquire_windows_mutex(self) -> None:
        with _HELD_IDENTITIES_LOCK:
            if self.identity in _HELD_IDENTITIES:
                raise self._in_use_error()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        name = f"Local\\RecruitingTalentWorkbench-{self.identity}"
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, True, name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "无法创建应用互斥锁")
        if ctypes.get_last_error() == 183:
            wait_result = kernel32.WaitForSingleObject(handle, 500)
            if wait_result not in {0x00000000, 0x00000080}:
                kernel32.CloseHandle(handle)
                raise self._in_use_error()
        self._mutex_handle = int(handle)
        with _HELD_IDENTITIES_LOCK:
            _HELD_IDENTITIES.add(self.identity)

    @staticmethod
    def _close_windows_handle(handle: int) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel32.ReleaseMutex.restype = ctypes.c_bool
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        pointer = ctypes.c_void_p(handle)
        kernel32.ReleaseMutex(pointer)
        kernel32.CloseHandle(pointer)

    def _in_use_error(self) -> ApplicationLockError:
        return ApplicationLockError(
            "当前数据库正在被其他实例使用。请先关闭另一个实例。\n"
            f"数据库路径：{self.database_path}"
        )

    @staticmethod
    def _lock_file(handle: BinaryIO) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_file(handle: BinaryIO) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
