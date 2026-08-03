#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Ensures that Ollama is running before LLM modules attempt to use it.
Works on Windows, WSL, Linux.

Behavior:
- Check if port 11434 is open
- If not, start `ollama serve` in the background
- Wait until it's accepting connections
"""

from __future__ import annotations
import subprocess
import socket
import time
import os
import sys

from ultimate_pipeline.config.settings import SETTINGS


def _is_ollama_running() -> bool:
    """Check if Ollama API is listening on localhost:11434."""
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.5):
            return True
    except OSError:
        return False


def _start_ollama_background():
    """
    Start ollama serve in background.
    Works on Linux/WSL/Windows (PowerShell).
    """
    print("🟡 Ollama not running → starting 'ollama serve'...")

    if sys.platform.startswith("win"):
        # Windows / PowerShell style
        subprocess.Popen(
            ["ollama", "serve"],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        # Linux / WSL / Mac
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    # Wait until it starts responding
    timeout = SETTINGS.OLLAMA_STARTUP_TIMEOUT
    start = time.time()

    print(f"⏳ Waiting up to {timeout}s for Ollama…")

    while time.time() - start < timeout:
        if _is_ollama_running():
            print("🟢 Ollama is now running!")
            return
        time.sleep(0.4)

    print("⚠️ Warning: Ollama did not start in time. LLM requests may fail.")


def ensure_ollama_ready():
    """
    The main API for external callers.
    """
    if not SETTINGS.AUTO_START_OLLAMA:
        print("⏭ AUTO_START_OLLAMA disabled in settings.")
        return

    if _is_ollama_running():
        print("🟢 Ollama is already running.")
    else:
        _start_ollama_background()
