"""
Console encoding hardening for Windows and other platforms.

Ensures stdout/stderr (and logging handlers pointing to them) never raise
UnicodeEncodeError when emitting non-ASCII characters.
"""
from __future__ import annotations

import io
import logging
import sys
from io import TextIOWrapper
from typing import Optional, Any

_ENSURED = False


class _SafeProxy:
    """Fallback stream proxy that backslash-escapes on encoding errors."""

    def __init__(self, base):
        self._base = base
        self.encoding = "utf-8"
        self.errors = "backslashreplace"
        self.buffer = getattr(base, "buffer", None)

    def write(self, data):
        try:
            return self._base.write(data)
        except Exception:
            try:
                if isinstance(data, bytes):
                    text = data.decode("utf-8", errors="backslashreplace")
                else:
                    text = str(data)
                safe = text.encode("ascii", errors="backslashreplace").decode("ascii")
                return self._base.write(safe)
            except Exception:
                return None

    def flush(self):
        try:
            return self._base.flush()
        except Exception:
            return None

    def isatty(self):
        try:
            return self._base.isatty()
        except Exception:
            return False

    def fileno(self):
        try:
            return self._base.fileno()
        except Exception:
            return -1

    def __getattr__(self, name):
        return getattr(self._base, name)


def _safe_wrap_stream(stream) -> None | TextIOWrapper[Any | None] | _SafeProxy | Any:
    """
    Return a stream that will not raise UnicodeEncodeError on writes.
    Preference order:
      1) reconfigure to utf-8/backslashreplace (Python 3.7+)
      2) wrap buffer with TextIOWrapper (utf-8/backslashreplace)
      3) _SafeProxy fallback
    """
    if stream is None:
        return None

    try:
        enc = getattr(stream, "encoding", "") or ""
        errs = getattr(stream, "errors", "") or ""
        if enc.lower() == "utf-8" and errs == "backslashreplace":
            return stream
    except Exception:
        pass

    try:
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
            return stream
    except Exception:
        pass

    try:
        buf = getattr(stream, "buffer", None)
        if buf is not None:
            return io.TextIOWrapper(
                buf, encoding="utf-8", errors="backslashreplace", line_buffering=True
            )
    except Exception:
        pass

    return _SafeProxy(stream)


def _retarget_logging(old_out, old_err, new_out, new_err) -> None:
    """Point existing StreamHandlers at the new safe streams."""
    for logger in (logging.getLogger(), logging.root):
        for handler in list(getattr(logger, "handlers", [])):
            stream = getattr(handler, "stream", None)
            try:
                if stream is old_out:
                    handler.setStream(new_out)
                elif stream is old_err:
                    handler.setStream(new_err)
            except Exception:
                continue


def ensure_utf8_console() -> None:
    """Force stdout/stderr to UTF-8/backslashreplace; idempotent."""
    global _ENSURED
    if _ENSURED:
        return

    # Windows-specific: Force console code page to 65001 (UTF-8)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass

    orig_out, orig_err = sys.stdout, sys.stderr
    safe_out = _safe_wrap_stream(orig_out)
    safe_err = _safe_wrap_stream(orig_err)

    if safe_out is not None:
        sys.stdout = safe_out
    if safe_err is not None:
        sys.stderr = safe_err

    _retarget_logging(orig_out, orig_err, sys.stdout, sys.stderr)
    _ENSURED = True
