"""Own a kernel and its descendants, so cancellation releases child processes."""

from __future__ import annotations

import os
import signal


class PosixProcessGroup:
    def __init__(self, pid: int):
        self.pid = pid

    def close(self):
        try:
            # This exact group ID is created by kernel setsid(). Never query
            # and signal the inherited parent group. The leader can already be
            # dead while its descendants still belong to this group. Its PID
            # remains reserved until the supervisor joins the Process below.
            os.killpg(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class WindowsJobGroup:
    def __init__(self, pid: int):
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("per_process_time", ctypes.c_longlong), ("per_job_time", ctypes.c_longlong),
                ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
                ("maximum_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                ("scheduling_class", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "read_operations", "write_operations", "other_operations",
                "read_bytes", "write_bytes", "other_bytes",
            )]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits), ("io", IoCounters),
                ("process_memory_limit", ctypes.c_size_t), ("job_memory_limit", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
            ]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.api.TerminateJobObject.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        process_handle = None
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            # Assignment needs PROCESS_SET_QUOTA | PROCESS_TERMINATE. Nested
            # jobs keep each session inside the outer Tauri sidecar job too.
            process_handle = self.api.OpenProcess(0x0101, False, pid)
            if not process_handle or not self.api.AssignProcessToJobObject(self.handle, process_handle):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.api.CloseHandle(self.handle)
            self.handle = None
            raise
        finally:
            if process_handle:
                self.api.CloseHandle(process_handle)

    def close(self):
        import ctypes

        if self.handle is not None:
            handle, self.handle = self.handle, None
            try:
                if not self.api.TerminateJobObject(handle, 1):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                self.api.CloseHandle(handle)


def own_process_group(pid: int):
    return WindowsJobGroup(pid) if os.name == "nt" else PosixProcessGroup(pid)


def initialize_kernel_group():
    if os.name != "nt":
        os.setsid()


def exit_kernel_and_children():
    if os.name != "nt":
        try:
            if os.getpgid(0) == os.getpid():
                os.killpg(os.getpid(), signal.SIGKILL)
        except ProcessLookupError:
            pass
    os._exit(75)
