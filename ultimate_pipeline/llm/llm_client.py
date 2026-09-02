#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM client for the Ultimate OSM→CARLA pipeline.

Backend: local Ollama only.

Usage:
    from ultimate_pipeline.llm.llm_client import LLMClient

    client = LLMClient()
    answer = client.ask("Check this XODR ...")
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from ultimate_pipeline.llm.ollama_bootstrap import ensure_ollama_ready


@dataclass
class LLMConfig:
    """
    Configuration for the local LLM (Ollama).
    """
    backend: str = os.getenv("ULTIMATE_LLM_BACKEND", "ollama")   # ← ADD THIS LINE
    model: str = os.getenv("ULTIMATE_LLM_MODEL", "deepseek-coder:6.7b")
    timeout_sec: int = 120
    max_prompt_chars: int = 8000



class LLMClient:
    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig()

        # 🔒 Backend selector (future-proof)
        if self.config.backend != "ollama":
            raise RuntimeError(f"Unsupported LLM backend: {self.config.backend}")

        # Check installation first: ensure_ollama_ready() would otherwise try
        # to `subprocess.Popen(["ollama", "serve"], ...)` when Ollama isn't
        # running, which raises an unhandled FileNotFoundError (not caught
        # anywhere in ollama_bootstrap.py) if the binary isn't installed at
        # all -- masking this intended, friendlier error with an uglier one.
        if shutil.which("ollama") is None:
            raise RuntimeError("Ollama is not installed or not in PATH.")

        # Make sure Ollama is running before sending prompts
        ensure_ollama_ready()


    def ask(self, prompt: str) -> str:
        """
        Send a plain-text prompt to the local Ollama model and return its response.
        """
        if len(prompt) > self.config.max_prompt_chars:
            prompt = prompt[: self.config.max_prompt_chars] + "\n\n[...TRUNCATED INPUT...]"

        try:
            proc = subprocess.run(
                ["ollama", "run", self.config.model],
                input=prompt.encode("utf-8"),
                capture_output=True,
                timeout=self.config.timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"Ollama timed out after {self.config.timeout_sec}s") from e
        except OSError as e:
            raise RuntimeError(f"Failed to run 'ollama': {e}") from e

        if proc.returncode != 0:
            stderr = proc.stderr.decode("utf-8", errors="ignore")
            raise RuntimeError(f"Ollama returned non-zero exit code {proc.returncode}:\n{stderr}")

        return proc.stdout.decode("utf-8", errors="ignore").strip()
