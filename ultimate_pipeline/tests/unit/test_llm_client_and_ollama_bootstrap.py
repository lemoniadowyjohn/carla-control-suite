# ultimate_pipeline/llm/llm_client.py + ollama_bootstrap.py -- zero prior
# test coverage. Live: main_pipeline.py imports LLMQualityGate (already
# tested with a mocked LLMClient, see test_llm_quality_gate.py), and
# LLMQualityGate constructs a real LLMClient() by default, which imports
# and calls ensure_ollama_ready() from this module. ENABLE_LLM_REVIEW
# defaults to False and the whole call is wrapped in a catch-all
# try/except in main_pipeline.py, so this is advisory/best-effort, not a
# pipeline-blocking gate -- but it's still real, reachable code with a
# real bug.
#
# Real bug found: LLMClient.__init__ called ensure_ollama_ready() BEFORE
# checking shutil.which("ollama"). ensure_ollama_ready() -> when Ollama
# isn't already running -> _start_ollama_background() ->
# subprocess.Popen(["ollama", "serve"], ...), which raises an unhandled
# FileNotFoundError if the "ollama" binary isn't installed at all (not
# caught anywhere in ollama_bootstrap.py). This masked the intended,
# friendlier "Ollama is not installed or not in PATH." RuntimeError the
# very next line was clearly meant to raise -- confirmed this is the
# exact live condition on this machine (`where ollama` -> not found).
# Fixed: check shutil.which("ollama") FIRST, before attempting to
# start/probe it.
from __future__ import annotations

import socket
import subprocess
from unittest import mock

import pytest

from ultimate_pipeline.llm import llm_client as lc
from ultimate_pipeline.llm import ollama_bootstrap as ob


# ---------------------------------------------------------------------------
# LLMClient.__init__ ordering bug
# ---------------------------------------------------------------------------

def test_missing_ollama_binary_raises_friendly_error_not_file_not_found(monkeypatch):
    monkeypatch.setattr(lc.shutil, "which", lambda name: None)
    called = {"ensure_ready": False}
    monkeypatch.setattr(
        lc, "ensure_ollama_ready", lambda: called.__setitem__("ensure_ready", True)
    )

    with pytest.raises(RuntimeError, match="Ollama is not installed or not in PATH"):
        lc.LLMClient()

    # The fix's whole point: don't even attempt to start/probe Ollama once
    # we already know the binary isn't installed.
    assert called["ensure_ready"] is False


def test_unsupported_backend_raises_before_touching_ollama_at_all(monkeypatch):
    calls = []
    monkeypatch.setattr(lc.shutil, "which", lambda name: calls.append("which") or "/usr/bin/ollama")
    monkeypatch.setattr(lc, "ensure_ollama_ready", lambda: calls.append("ensure_ready"))

    with pytest.raises(RuntimeError, match="Unsupported LLM backend"):
        lc.LLMClient(config=lc.LLMConfig(backend="openai"))

    assert calls == []


def test_init_succeeds_when_ollama_available(monkeypatch):
    monkeypatch.setattr(lc.shutil, "which", lambda name: "/usr/bin/ollama")
    monkeypatch.setattr(lc, "ensure_ollama_ready", lambda: None)

    client = lc.LLMClient()

    assert client.config.backend == "ollama"


# ---------------------------------------------------------------------------
# LLMClient.ask()
# ---------------------------------------------------------------------------

def _make_client(monkeypatch) -> lc.LLMClient:
    monkeypatch.setattr(lc.shutil, "which", lambda name: "/usr/bin/ollama")
    monkeypatch.setattr(lc, "ensure_ollama_ready", lambda: None)
    return lc.LLMClient()


def test_ask_truncates_overlong_prompt(monkeypatch):
    client = _make_client(monkeypatch)
    client.config.max_prompt_chars = 10

    captured = {}

    def fake_run(cmd, input, capture_output, timeout, check):
        captured["input"] = input
        return subprocess.CompletedProcess(cmd, 0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(lc.subprocess, "run", fake_run)

    client.ask("x" * 100)

    sent = captured["input"].decode("utf-8")
    assert len(sent) < 100
    assert "[...TRUNCATED INPUT...]" in sent


def test_ask_returns_stripped_stdout(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        lc.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], 0, stdout=b"  hello world  \n", stderr=b""),
    )

    result = client.ask("hi")

    assert result == "hello world"


def test_ask_raises_on_nonzero_exit(monkeypatch):
    client = _make_client(monkeypatch)
    monkeypatch.setattr(
        lc.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"model not found"),
    )

    with pytest.raises(RuntimeError, match="model not found"):
        client.ask("hi")


def test_ask_raises_friendly_error_on_timeout(monkeypatch):
    client = _make_client(monkeypatch)

    def fake_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd=["ollama"], timeout=1)

    monkeypatch.setattr(lc.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="timed out"):
        client.ask("hi")


def test_ask_raises_friendly_error_on_os_error(monkeypatch):
    client = _make_client(monkeypatch)

    def fake_run(*a, **k):
        raise OSError("boom")

    monkeypatch.setattr(lc.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="Failed to run 'ollama'"):
        client.ask("hi")


# ---------------------------------------------------------------------------
# ollama_bootstrap
# ---------------------------------------------------------------------------

def test_is_ollama_running_true_when_connection_succeeds(monkeypatch):
    monkeypatch.setattr(ob.socket, "create_connection", mock.MagicMock())
    assert ob._is_ollama_running() is True


def test_is_ollama_running_false_on_os_error(monkeypatch):
    def fake_connect(*a, **k):
        raise OSError("refused")

    monkeypatch.setattr(ob.socket, "create_connection", fake_connect)
    assert ob._is_ollama_running() is False


def test_ensure_ollama_ready_noop_when_auto_start_disabled(monkeypatch, capsys):
    monkeypatch.setattr(ob.SETTINGS, "AUTO_START_OLLAMA", False)
    called = []
    monkeypatch.setattr(ob, "_is_ollama_running", lambda: called.append("checked"))

    ob.ensure_ollama_ready()

    assert called == []
    assert "disabled" in capsys.readouterr().out


def test_ensure_ollama_ready_skips_start_when_already_running(monkeypatch):
    monkeypatch.setattr(ob.SETTINGS, "AUTO_START_OLLAMA", True)
    monkeypatch.setattr(ob, "_is_ollama_running", lambda: True)
    started = []
    monkeypatch.setattr(ob, "_start_ollama_background", lambda: started.append(True))

    ob.ensure_ollama_ready()

    assert started == []


def test_ensure_ollama_ready_starts_when_not_running(monkeypatch):
    monkeypatch.setattr(ob.SETTINGS, "AUTO_START_OLLAMA", True)
    monkeypatch.setattr(ob, "_is_ollama_running", lambda: False)
    started = []
    monkeypatch.setattr(ob, "_start_ollama_background", lambda: started.append(True))

    ob.ensure_ollama_ready()

    assert started == [True]
