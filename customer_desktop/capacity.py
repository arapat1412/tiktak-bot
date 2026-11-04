"""Admission limits for new workers. Never stops or retries a public action."""

import ctypes
import os
import shutil

MAX_PARALLEL = 50
MIB = 1024 * 1024


def parallel_limit(value):
    try:
        return max(1, min(MAX_PARALLEL, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 1


def launch_interval(value):
    try:
        value = float(value)
        return value if 0 <= value <= 60 else 2.0
    except (TypeError, ValueError, OverflowError):
        return 2.0


def sample_capacity(root):
    """Called on a dedicated background pool; paths may be on slow storage."""
    free = shutil.disk_usage(root).free
    available = total = None
    if os.name == "nt":

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_uint32),
                ("load", ctypes.c_uint32),
                *[
                    (name, ctypes.c_uint64)
                    for name in (
                        "total",
                        "available",
                        "page_total",
                        "page_available",
                        "virtual_total",
                        "virtual_available",
                        "extended_available",
                    )
                ],
            ]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        api = ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx
        api.argtypes = [ctypes.POINTER(MemoryStatus)]
        api.restype = ctypes.c_int
        if not api(ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        total, available = status.total, status.available
    elif hasattr(os, "sysconf"):
        total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        available = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    return dict(
        disk_free=free,
        memory_available=available,
        memory_total=total,
        reason=capacity_reason(free, available, total),
    )


def capacity_reason(free, available, total):
    reason = ""
    if free < 512 * MIB:
        reason = "Đĩa dữ liệu còn dưới 512 MB. Dọn dung lượng để nhận việc mới."
    elif available is None or total is None:
        reason = "Chưa đo được RAM trống. Tạm chờ trước khi mở worker mới."
    elif available < max(512 * MIB, total * 0.05):
        reason = "RAM trống thấp (dưới 512 MB hoặc 5%). Tạm chờ nhận việc mới."
    return reason
