"""
Backward compatibility wrapper for console encoding.
Logic moved to ultimate_pipeline.utils.console_encoding.
"""
from ultimate_pipeline.utils.console_encoding import ensure_utf8_console as _ensure

def enable():
    """Enable UTF-8 console output (legacy entrypoint)."""
    _ensure()
