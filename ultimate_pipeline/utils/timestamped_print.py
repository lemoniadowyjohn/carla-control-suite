from __future__ import annotations

import builtins
import datetime
import threading
import sys
from typing import Any, TextIO

_lock = threading.Lock()
_enabled = False
_original_print = builtins.print


def disable_timestamped_print() -> None:
    """Restore the original builtins.print()."""
    global _enabled
    if not _enabled:
        return
    builtins.print = _original_print
    _enabled = False


def enable_timestamped_print(fmt: str = "%Y-%m-%d %H:%M:%S") -> None:
    """Prefix all print() output with a timestamp.

    Robust against Windows console encodings (e.g., cp1252) that cannot print emojis.
    Never crashes on UnicodeEncodeError; falls back to safe output.
    """
    global _enabled
    if _enabled:
        return

    def _safe_write(stream: TextIO, text: str) -> None:
        """
        Write text to a stream without raising UnicodeEncodeError.
        Preferred fallback: write UTF-8 bytes to stream.buffer (when available).
        Final fallback: ASCII with backslash escapes.
        """
        try:
            stream.write(text)
            return
        except UnicodeEncodeError:
            pass

        # Fallback 1: write UTF-8 bytes if possible (bypasses text encoding)
        try:
            if hasattr(stream, "buffer") and stream.buffer is not None:
                stream.buffer.write(text.encode("utf-8", errors="backslashreplace"))
                return
        except Exception:
            pass

        # Fallback 2: sanitize to ASCII escapes
        try:
            sanitized = text.encode("ascii", errors="backslashreplace").decode("ascii")
            stream.write(sanitized)
        except Exception:
            # Nothing else we can do safely.
            return

    def _ts_print(*args: Any, **kwargs: Any) -> None:
        with _lock:
            ts = datetime.datetime.now().strftime(fmt)

            sep = kwargs.pop("sep", " ")
            end = kwargs.pop("end", "\n")
            file = kwargs.pop("file", None)
            flush = bool(kwargs.pop("flush", False))

            # Keep compatibility with print(file=...)
            stream: TextIO = file if file is not None else sys.stdout

            # Build the message like print() would
            parts = [f"[{ts}]"]
            if args:
                parts.append(sep.join(str(a) for a in args))
            msg = (sep.join(parts) if len(parts) > 1 else parts[0]) + end

            _safe_write(stream, msg)

            if flush:
                try:
                    stream.flush()
                except Exception:
                    pass

    builtins.print = _ts_print
    _enabled = True
