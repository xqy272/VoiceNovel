"""LLM backend implementations: Mock, OpenAI-compatible, DeepSeek, Anthropic."""

from __future__ import annotations

import asyncio
import json
import time

from vn_core.llm_gateway import LLMRequest, LLMResponse

# ── Mock ──────────────────────────────────────────────────────────────────────

class MockLLMBackend:
    def __init__(self):
        self.engine = "mock"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        await asyncio.sleep(0.01)
        task_handlers = {
            "speaker_attribution": self._mock_speaker,
            "reading_style": self._mock_style,
            "text_adaptation": self._mock_adaptation,
            "character_extraction": self._mock_characters,
            "scene_summary": self._mock_scene,
        }
        handler = task_handlers.get(request.task, self._mock_generic)
        content = handler(request)
        return LLMResponse(
            task=request.task, content=content, model=self.engine, latency_ms=10.0,
        )

    def _mock_speaker(self, request: LLMRequest) -> str:
        return json.dumps(
            {
                "speaker_candidate": None,
                "speaker_id": "char_narrator",
                "speaker_confidence": 0.5,
                "reading_style": {
                    "emotion": "neutral",
                    "intensity": 0.0,
                    "prosody_hint": "normal_pause",
                },
                "evidence": ["mock: no explicit speaker tag found"],
            },
            ensure_ascii=False,
        )

    def _mock_style(self, request: LLMRequest) -> str:
        return json.dumps(
            {
                "emotion": "neutral",
                "intensity": 0.0,
                "prosody_hint": "normal_pause",
            },
            ensure_ascii=False,
        )

    def _mock_adaptation(self, request: LLMRequest) -> str:
        return json.dumps({"operations": []}, ensure_ascii=False)

    def _mock_characters(self, request: LLMRequest) -> str:
        return json.dumps({"characters": []}, ensure_ascii=False)

    def _mock_scene(self, request: LLMRequest) -> str:
        return json.dumps(
            {"summary": "A scene unfolds.", "active_characters": []},
            ensure_ascii=False,
        )

    def _mock_generic(self, request: LLMRequest) -> str:
        return json.dumps({"result": "mock response"}, ensure_ascii=False)


# ── OpenAI-compatible base ────────────────────────────────────────────────────

class OpenAILLMBackend:
    """OpenAI and any OpenAI-compatible API (DeepSeek, vLLM, Ollama, etc.)."""

    def __init__(self, api_key: str = "", model: str = "gpt-4o-mini", base_url: str = ""):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url or "https://api.openai.com/v1"
        self.engine = "openai"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        try:
            import httpx
        except ImportError:
            return LLMResponse(
                task=request.task, content="", model=self.engine, error="httpx not installed",
            )

        if not self.api_key:
            return LLMResponse(
                task=request.task, content="", model=self.engine, error="no API key configured",
            )

        messages_payload = [{"role": m.role, "content": m.content} for m in request.messages]
        model_name = request.model or self.model

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model_name,
                        "messages": messages_payload,
                        "temperature": request.temperature,
                        "max_tokens": request.max_tokens,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                latency = (time.time() - start) * 1000
                return LLMResponse(
                    task=request.task, content=content, model=model_name,
                    usage=usage, latency_ms=latency,
                )
        except Exception as e:
            return LLMResponse(task=request.task, content="", model=self.engine, error=str(e))


# ── DeepSeek ──────────────────────────────────────────────────────────────────

class DeepSeekLLMBackend(OpenAILLMBackend):
    """DeepSeek API — OpenAI-compatible endpoint at api.deepseek.com."""

    def __init__(self, api_key: str = "", model: str = "deepseek-chat"):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url="https://api.deepseek.com/v1",
        )
        self.engine = "deepseek"


# ── Anthropic (Claude) ───────────────────────────────────────────────────────

class AnthropicLLMBackend:
    """Anthropic Claude backend via /v1/messages API."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "claude-sonnet-4-6",
        base_url: str = "https://api.anthropic.com",
        anthropic_version: str = "2023-06-01",
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.anthropic_version = anthropic_version
        self.engine = "claude"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        try:
            import httpx
        except ImportError:
            return LLMResponse(
                task=request.task, content="", model=self.engine, error="httpx not installed",
            )

        if not self.api_key:
            return LLMResponse(
                task=request.task, content="", model=self.engine, error="no API key configured",
            )

        system_prompt = ""
        user_messages = []
        for m in request.messages:
            if m.role == "system":
                system_prompt = m.content
            else:
                user_messages.append({"role": m.role, "content": m.content})

        model_name = request.model or self.model
        body: dict = {
            "model": model_name,
            "max_tokens": request.max_tokens,
            "messages": user_messages,
        }
        if system_prompt:
            body["system"] = system_prompt
        body["temperature"] = max(request.temperature, 0.0)

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.base_url}/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": self.anthropic_version,
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                resp.raise_for_status()
                data = resp.json()
                content = ""
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        content += block["text"]
                usage = data.get("usage", {})
                latency = (time.time() - start) * 1000
                return LLMResponse(
                    task=request.task, content=content, model=model_name,
                    usage=usage, latency_ms=latency,
                )
        except Exception as e:
            return LLMResponse(task=request.task, content="", model=self.engine, error=str(e))
