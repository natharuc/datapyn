"""Separate Windows inherited standard handles from the supervisor protocol."""

from __future__ import annotations

import os


def set_windows_standard_handle(handle_id: int, file_descriptor: int):
    if os.name != "nt":
        return
    import ctypes
    import msvcrt

    setter = ctypes.WinDLL("kernel32", use_last_error=True).SetStdHandle
    setter.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
    setter.restype = ctypes.c_int
    if not setter(ctypes.c_ulong(handle_id), msvcrt.get_osfhandle(file_descriptor)):
        raise ctypes.WinError(ctypes.get_last_error())


def detach_child_stdin():
    """Keep the existing Python stdin stream, but give spawned kernels NUL.

    On Windows multiprocessing closes its inherited stdin before kernel_main.
    Closing a handle to the pipe while the supervisor is reading that same pipe
    can block bootstrap. SetStdHandle only changes handles inherited by future
    children; it leaves the already-open protocol stream usable. Keep NUL open
    for the supervisor lifetime. Kernels also cannot consume control requests.
    """
    if os.name != "nt":
        return None
    null_input = open(os.devnull, "rb")
    try:
        set_windows_standard_handle(-10, null_input.fileno())
    except BaseException:
        null_input.close()
        raise
    return null_input


def isolate_kernel_output():
    """Discard native writes; Python prints use the typed output stream."""
    null_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(null_fd, 1)
        os.dup2(null_fd, 2)
        # subprocess on Windows inherits Win32 handles, not only CRT fds.
        set_windows_standard_handle(-11, 1)
        set_windows_standard_handle(-12, 2)
    finally:
        os.close(null_fd)
