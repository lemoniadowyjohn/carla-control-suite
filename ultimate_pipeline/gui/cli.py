"""CLI entry point for the CARLA Ops Studio GUI.

This module provides the `carla-ops` console script entry point. It is
intentionally minimal and defers all GUI logic to the Qt application shell.

Usage:
    carla-ops              # Launch GUI in offline/mock mode
    carla-ops --help       # Show help
    carla-ops --version    # Show version
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="carla-ops",
        description="CARLA Ops Studio - Qt GUI for CARLA 0.9.16 operations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  carla-ops                    Launch in offline/mock mode (default)
  carla-ops --live             Request live simulator connection (requires lease)
  carla-ops --profile dark     Start with dark theme
  carla-ops --config path      Use custom preferences file

Environment:
  QT_QPA_PLATFORM=offscreen   Force offscreen rendering (CI/testing)
  CARLA_GUI_PROFILE           Default preferences profile name
  CARLA_GUI_CONFIG_DIR        Override config directory location
""",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Attempt live simulator connection (requires exclusive authority lease)",
    )
    parser.add_argument(
        "--profile",
        choices=["light", "dark", "system"],
        default="system",
        help="Initial UI theme (default: system)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to preferences JSON file (default: platform config dir / carla_ops_gui.json)",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit",
    )
    parser.add_argument(
        "--verify-install",
        action="store_true",
        help="Verify installation dependencies and exit",
    )
    return parser


def verify_install() -> tuple[bool, list[str]]:
    """Verify that all required dependencies are importable.

    Returns:
        (success, messages) where success is True if all checks pass.
    """
    messages = []
    ok = True

    # Check Python version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    messages.append(f"Python: {py_version}")
    if sys.version_info < (3, 10):
        messages.append("  WARNING: Python >= 3.10 required")
        ok = False

    # Check CARLA client
    try:
        import carla
        version = getattr(carla, "__version__", "unknown")
        messages.append(f"CARLA client: {version}")
    except ImportError as exc:
        messages.append(f"  CARLA client NOT available: {exc}")
        ok = False

    # Check PyQt6
    try:
        from PyQt6 import QtCore
        messages.append(f"PyQt6: {QtCore.PYQT_VERSION_STR}")
    except ImportError as exc:
        messages.append(f"  PyQt6 NOT available: {exc}")
        ok = False

    # Check OpenCV (headless)
    try:
        import cv2
        messages.append(f"OpenCV: {cv2.__version__}")
    except ImportError as exc:
        messages.append(f"  OpenCV NOT available: {exc}")
        ok = False

    # Check numpy
    try:
        import numpy
        messages.append(f"numpy: {numpy.__version__}")
    except ImportError as exc:
        messages.append(f"  numpy NOT available: {exc}")
        ok = False

    return ok, messages


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from ultimate_pipeline import __version__
        print(f"carla-ops {__version__}")
        return 0

    if args.verify_install:
        ok, messages = verify_install()
        for m in messages:
            print(m)
        return 0 if ok else 1

    # Deferred import so --verify-install and --version work without Qt
    from ultimate_pipeline.gui.shell.main_window import create_application, MainWindow
    from ultimate_pipeline.gui.shell.services import build_registry
    from ultimate_pipeline.gui.shell.preferences import UIPreferences, load

    app = create_application(sys.argv)

    # Load preferences
    prefs_path = args.config
    if prefs_path is None:
        # Default: platform config directory
        if sys.platform == "win32":
            base = Path.home() / "AppData" / "Local" / "CARLA_Ops_Studio"
        else:
            base = Path.home() / ".config" / "carla_ops_studio"
        base.mkdir(parents=True, exist_ok=True)
        prefs_path = base / "carla_ops_gui.json"

    prefs = UIPreferences()
    if prefs_path.exists():
        try:
            prefs = load(prefs_path)
        except Exception:
            pass  # Use defaults

    # Apply theme preference
    if args.profile != "system":
        prefs.theme = args.profile

    registry = build_registry()

    window = MainWindow(registry, prefs_path=prefs_path)
    window.show()

    # If --live is requested, navigate to connection diagnostics
    if args.live:
        window.navigate("03_connection_diagnostics")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())