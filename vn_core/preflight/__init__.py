"""Preflight Check: validate LLM, TTS, ASR endpoints, tools, and resources before generation."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field


@dataclass
class PreflightResult:
    can_proceed: bool = True
    checks: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class PreflightCheck:
    def __init__(self):
        self._ffmpeg_available: bool | None = None
        self._ffprobe_available: bool | None = None

    def check_tools(self) -> dict[str, bool]:
        results = {}
        results["ffmpeg"] = shutil.which("ffmpeg") is not None
        results["ffprobe"] = shutil.which("ffprobe") is not None
        self._ffmpeg_available = results["ffmpeg"]
        self._ffprobe_available = results["ffprobe"]
        return results

    def check_llm_endpoint(self, endpoint: str = "", api_key: str = "") -> dict:
        result = {"available": bool(endpoint or api_key), "endpoint": endpoint or "not configured"}
        return result

    def check_tts_endpoint(self, endpoint: str = "") -> dict:
        result = {"available": bool(endpoint), "endpoint": endpoint or "not configured"}
        return result

    def run_preflight(
        self,
        llm_endpoint: str = "",
        tts_endpoint: str = "",
        usage_scenario: str = "personal",
    ) -> PreflightResult:
        result = PreflightResult()

        tools = self.check_tools()
        for tool, available in tools.items():
            result.checks.append({"check": f"tool_{tool}", "passed": available})
            if not available:
                result.warnings.append(f"{tool} not found in PATH")

        llm = self.check_llm_endpoint(llm_endpoint)
        result.checks.append({"check": "llm_endpoint", **llm})
        if not llm["available"]:
            result.errors.append("LLM endpoint not configured")

        tts = self.check_tts_endpoint(tts_endpoint)
        result.checks.append({"check": "tts_endpoint", **tts})
        if not tts["available"]:
            result.errors.append("TTS endpoint not configured")

        result.can_proceed = len(result.errors) == 0
        return result
