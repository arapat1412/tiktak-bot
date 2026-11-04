"""Windows kernel ownership: PID identity and kill-on-close job containment."""

import os
import ctypes
from ctypes import wintypes as w

if os.name == "nt":
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.argtypes = (w.DWORD, w.BOOL, w.DWORD)
    k32.OpenProcess.restype = w.HANDLE
    k32.CloseHandle.argtypes = (w.HANDLE,)
    k32.GetProcessTimes.argtypes = (
        w.HANDLE,
        ctypes.POINTER(w.FILETIME),
        ctypes.POINTER(w.FILETIME),
        ctypes.POINTER(w.FILETIME),
        ctypes.POINTER(w.FILETIME),
    )
    k32.WaitForSingleObject.argtypes = (w.HANDLE, w.DWORD)
    k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, w.LPCWSTR)
    k32.CreateJobObjectW.restype = w.HANDLE
    k32.SetInformationJobObject.argtypes = (
        w.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        w.DWORD,
    )
    k32.AssignProcessToJobObject.argtypes = (w.HANDLE, w.HANDLE)
    k32.TerminateJobObject.argtypes = (w.HANDLE, w.UINT)
    k32.QueryInformationJobObject.argtypes = (
        w.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        w.DWORD,
        ctypes.c_void_p,
    )


def process_identity(pid):
    """None when gone, 'unknown' when permission prevents checking. Never kill by PID."""
    if not pid:
        return None
    if os.name != "nt":
        try:
            return str(os.stat(f"/proc/{pid}").st_ctime_ns)
        except FileNotFoundError:
            return None
    handle = k32.OpenProcess(0x1000 | 0x100000, False, int(pid))
    if not handle:
        return None if ctypes.get_last_error() == 87 else "unknown"
    try:
        if k32.WaitForSingleObject(handle, 0) == 0:
            return None
        fields = [w.FILETIME() for _ in range(4)]
        if not k32.GetProcessTimes(handle, *(ctypes.byref(f) for f in fields)):
            return "unknown"
        return str((fields[0].dwHighDateTime << 32) | fields[0].dwLowDateTime)
    finally:
        k32.CloseHandle(handle)


class JobGuard:
    def __init__(self, pid):
        self.handle = None
        if os.name != "nt":
            return

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64),
                ("job_time", ctypes.c_int64),
                ("flags", w.DWORD),
                ("minimum", ctypes.c_size_t),
                ("maximum", ctypes.c_size_t),
                ("active", w.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority", w.DWORD),
                ("scheduling", w.DWORD),
            ]

        class IO(ctypes.Structure):
            _fields_ = [
                (n, ctypes.c_uint64)
                for n in (
                    "read_ops",
                    "write_ops",
                    "other_ops",
                    "read_bytes",
                    "write_bytes",
                    "other_bytes",
                )
            ]

        class Extended(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits),
                ("io", IO),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process", ctypes.c_size_t),
                ("peak_job", ctypes.c_size_t),
            ]

        handle = k32.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        process = k32.OpenProcess(0x100 | 0x1, False, pid)
        try:
            if not k32.SetInformationJobObject(
                handle, 9, ctypes.byref(info), ctypes.sizeof(info)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if not process or not k32.AssignProcessToJobObject(handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
            self.handle = handle
        except BaseException:
            k32.CloseHandle(handle)
            raise
        finally:
            if process:
                k32.CloseHandle(process)

    def terminate(self):
        if self.handle:
            k32.TerminateJobObject(self.handle, 125)

    def empty(self):
        if not self.handle:
            return True

        class Accounting(ctypes.Structure):
            _fields_ = [
                (n, ctypes.c_int64)
                for n in ("user", "kernel", "period_user", "period_kernel")
            ] + [(n, w.DWORD) for n in ("faults", "total", "active", "terminated")]

        info = Accounting()
        if not k32.QueryInformationJobObject(
            self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None
        ):
            return False
        return info.active == 0

    def close(self):
        if self.handle:
            k32.CloseHandle(self.handle)
            self.handle = None
