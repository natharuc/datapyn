"""Cooperative export cancellation and throttled progress across kernel IPC."""

import time

EXPORT_METHODS = frozenset({"result.export", "result.export_text", "result.export_table",
                            "variable.archive.export", "variable.archive.import"})


class ExportCancelled(RuntimeError):
    pass


class ExportControl:
    def __init__(self, total, progress=None, cancelled=None):
        self.total = total
        self.progress = progress
        self.cancelled = cancelled or (lambda: False)
        self.last = 0.0
        self.current = 0
        self.phase = None
        self.notify(0, "preparing", force=True)

    def check(self):
        if self.cancelled():
            self.notify(self.current, "cancelled", force=True)
            raise ExportCancelled("Export cancelled")

    def notify(self, current, phase="writing", force=False):
        self.current = current
        now = time.monotonic()
        changed = phase != self.phase
        self.phase = phase
        if self.progress and (force or changed or now - self.last >= .1):
            self.progress({"phase": phase, "current": current, "total": self.total})
            self.last = now

    def advance(self, current):
        self.check()
        self.notify(current)

    def complete(self):
        self.notify(self.total, "completed", force=True)
