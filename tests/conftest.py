"""Shared test fixtures and real-backend detection for VoiceNovel tests."""

from __future__ import annotations

import os
import socket

import pytest


def _is_port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def has_real_tts() -> bool:
    env_tts = os.environ.get("VN_TTS_ENGINE", "").lower()
    if env_tts == "cosyvoice":
        endpoint = os.environ.get("VN_COSYVOICE_ENDPOINT", "http://localhost:50000")
        # Parse host:port from URL, handling IPv4 addresses correctly
        url_part = endpoint.split("//")[-1].rstrip("/")
        if ":" in url_part:
            host, port_str = url_part.rsplit(":", 1)
            try:
                port = int(port_str)
            except ValueError:
                port = 50000
        else:
            host = url_part
            port = 50000
        return _is_port_open(host, port)
    if env_tts == "edge_tts":
        return True
    return False


def has_real_llm() -> bool:
    return bool(os.environ.get("VN_LLM_API_KEY", ""))


def pytest_addoption(parser):
    parser.addoption(
        "--real-backends",
        action="store_true",
        default=False,
        help="Run tests that require real TTS and LLM backends",
    )


def pytest_collection_modifyitems(config, items):
    run_real = config.getoption("--real-backends", default=False)
    skip_opt_in = pytest.mark.skip(reason="requires --real-backends")
    skip_tts = pytest.mark.skip(reason="real TTS backend is not available")
    skip_llm = pytest.mark.skip(reason="real LLM backend is not available")

    for item in items:
        needs_tts = "real_tts" in item.keywords
        needs_llm = "real_llm" in item.keywords
        if (needs_tts or needs_llm) and not run_real:
            item.add_marker(skip_opt_in)
            continue
        if "real_tts" in item.keywords:
            if not has_real_tts():
                item.add_marker(skip_tts)
        if "real_llm" in item.keywords:
            if not has_real_llm():
                item.add_marker(skip_llm)
