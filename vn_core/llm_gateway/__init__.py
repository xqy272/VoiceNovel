"""LLM Gateway: unified interface for all LLM calls with rate limiting and fallback."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field


@dataclass
class LLMMessage:
    role: str
    content: str


@dataclass
class LLMRequest:
    task: str
    messages: list[LLMMessage]
    model: str = ""
    temperature: float = 0.3
    max_tokens: int = 2048
    context_capsule: dict | None = None
    cache_key: str = ""

    def compute_cache_key(self) -> str:
        if self.cache_key:
            return self.cache_key
        content = (
            f"{self.task}"
            f"|{self.model}"
            f"|{json.dumps(
                [{'r': m.role, 'c': m.content} for m in self.messages],
                ensure_ascii=False,
            )}"
            f"|{self.temperature}"
        )
        return hashlib.sha256(content.encode()).hexdigest()[:40]


@dataclass
class LLMResponse:
    task: str
    content: str
    model: str = ""
    usage: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    cached: bool = False
    error: str = ""


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
            task=request.task,
            content=content,
            model=self.engine,
            latency_ms=10.0,
        )

    def _mock_speaker(self, request: LLMRequest) -> str:
        return json.dumps({
            "speaker_candidate": None,
            "speaker_id": "char_narrator",
            "speaker_confidence": 0.5,
            "reading_style": {
                "emotion": "neutral",
                "intensity": 0.0,
                "prosody_hint": "normal_pause",
            },
            "evidence": ["mock: no explicit speaker tag found"],
        }, ensure_ascii=False)

    def _mock_style(self, request: LLMRequest) -> str:
        return json.dumps({
            "emotion": "neutral",
            "intensity": 0.0,
            "prosody_hint": "normal_pause",
        }, ensure_ascii=False)

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


class OpenAILLMBackend:
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
                task=request.task, content="", model=self.engine, error="httpx not installed"
            )

        if not self.api_key:
            return LLMResponse(
                task=request.task, content="", model=self.engine, error="no API key configured"
            )

        messages_payload = [{"role": m.role, "content": m.content} for m in request.messages]
        model_name = request.model or self.model

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
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
                    task=request.task,
                    content=content,
                    model=model_name,
                    usage=usage,
                    latency_ms=latency,
                )
        except Exception as e:
            return LLMResponse(task=request.task, content="", model=self.engine, error=str(e))


class LLMGateway:
    def __init__(self):
        self._backends: dict[str, object] = {}
        self._default_backend: str = "mock"
        self._fallback_order: list[str] = ["openai", "mock"]
        self._cache: dict[str, LLMResponse] = {}
        self._rate_last_call: dict[str, float] = {}
        self._rate_min_interval: dict[str, float] = {"openai": 0.5, "mock": 0.0}

        self._backends["mock"] = MockLLMBackend()

    def register_backend(self, name: str, backend: object, set_default: bool = False):
        self._backends[name] = backend
        if set_default:
            self._default_backend = name

    def configure_openai(self, api_key: str, model: str = "gpt-4o-mini", base_url: str = ""):
        backend = OpenAILLMBackend(api_key=api_key, model=model, base_url=base_url)
        self._backends["openai"] = backend
        if self._default_backend == "mock":
            self._default_backend = "openai"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        cache_key = request.compute_cache_key()
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            return LLMResponse(
                task=cached.task,
                content=cached.content,
                model=cached.model,
                usage=cached.usage,
                latency_ms=cached.latency_ms,
                cached=True,
            )

        backend_name = request.model if request.model in self._backends else self._default_backend
        result = await self._call_backend(backend_name, request)

        if result.error and backend_name != "mock":
            for fb_name in self._fallback_order:
                if fb_name == backend_name or fb_name not in self._backends:
                    continue
                result = await self._call_backend(fb_name, request)
                if not result.error:
                    break

        if not result.error:
            self._cache[cache_key] = result

        return result

    async def _call_backend(self, backend_name: str, request: LLMRequest) -> LLMResponse:
        backend = self._backends.get(backend_name)
        if not backend:
            return LLMResponse(
                task=request.task, content="", error=f"backend {backend_name} not found"
            )

        min_interval = self._rate_min_interval.get(backend_name, 0.0)
        last = self._rate_last_call.get(backend_name, 0.0)
        wait = min_interval - (time.time() - last)
        if wait > 0:
            await asyncio.sleep(wait)

        self._rate_last_call[backend_name] = time.time()
        return await backend.generate(request)

    def clear_cache(self):
        self._cache.clear()
