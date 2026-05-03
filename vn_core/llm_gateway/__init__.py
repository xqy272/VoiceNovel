"""LLM Gateway: unified interface for all LLM calls with rate limiting and fallback."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
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
    prompt_name: str = ""
    prompt_version: str = ""

    def compute_cache_key(self) -> str:
        if self.cache_key:
            return self.cache_key
        content = (
            f"{self.task}"
            f"|{self.model}"
            f"|{self.prompt_name}"
            f"|{self.prompt_version}"
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


# Import backends lazily to avoid circular imports
from vn_core.llm_gateway.backends import (
    AnthropicLLMBackend,
    DeepSeekLLMBackend,
    MockLLMBackend,
    OpenAILLMBackend,
)


class LLMGateway:
    def __init__(self, prompt_registry=None):
        self._backends: dict[str, object] = {}
        self._default_backend: str = "mock"
        self._fallback_order: list[str] = ["openai", "deepseek", "claude", "mock"]
        self._cache: dict[str, LLMResponse] = {}
        self._rate_last_call: dict[str, float] = {}
        self._rate_min_interval: dict[str, float] = {
            "openai": 0.5, "deepseek": 0.5, "claude": 0.5, "mock": 0.0,
        }
        self.prompt_registry = prompt_registry

        self._backends["mock"] = MockLLMBackend()

    def register_backend(self, name: str, backend: object, set_default: bool = False):
        self._backends[name] = backend
        if set_default:
            self._default_backend = name

    # ── convenience configurators ─────────────────────────────────────────

    def configure_openai(self, api_key: str, model: str = "gpt-4o-mini", base_url: str = ""):
        backend = OpenAILLMBackend(api_key=api_key, model=model, base_url=base_url)
        self._backends["openai"] = backend
        if self._default_backend == "mock":
            self._default_backend = "openai"

    def configure_deepseek(self, api_key: str, model: str = "deepseek-chat"):
        backend = DeepSeekLLMBackend(api_key=api_key, model=model)
        self._backends["deepseek"] = backend
        if self._default_backend == "mock":
            self._default_backend = "deepseek"

    def configure_claude(self, api_key: str, model: str = "claude-sonnet-4-6"):
        backend = AnthropicLLMBackend(api_key=api_key, model=model)
        self._backends["claude"] = backend
        if self._default_backend == "mock":
            self._default_backend = "claude"

    def configure_from_env(self):
        """Read VN_LLM_* env vars and configure the matching backend."""
        provider = os.environ.get("VN_LLM_PROVIDER", "").lower()
        api_key = os.environ.get("VN_LLM_API_KEY", "")
        model = os.environ.get("VN_LLM_MODEL", "")
        base_url = os.environ.get("VN_LLM_BASE_URL", "")

        if not provider:
            if api_key:
                import warnings
                warnings.warn("VN_LLM_API_KEY set but VN_LLM_PROVIDER not set; LLM will use mock")
            return
        if not api_key:
            import warnings
            warnings.warn(
                f"VN_LLM_PROVIDER={provider} but VN_LLM_API_KEY not set; LLM will use mock"
            )
            return

        if provider in ("openai", "gpt"):
            self.configure_openai(api_key, model=model or "gpt-4o-mini", base_url=base_url)
        elif provider in ("deepseek",):
            self.configure_deepseek(api_key, model=model or "deepseek-chat")
        elif provider in ("claude", "anthropic"):
            self.configure_claude(api_key, model=model or "claude-sonnet-4-6")
        elif base_url:
            backend = OpenAILLMBackend(api_key=api_key, model=model or "default", base_url=base_url)
            self._backends[provider] = backend
            if self._default_backend == "mock":
                self._default_backend = provider

    # ── prompt-based generation ───────────────────────────────────────────

    def build_from_prompt(
        self,
        prompt_name: str,
        prompt_version: str | None = None,
        template_vars: dict | None = None,
        task: str = "",
        model: str = "",
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> LLMRequest | None:
        """Build an LLMRequest from a registered prompt and template variables.

        Returns None if the prompt is not found in the registry.
        """
        if not self.prompt_registry:
            return None
        prompt_def = self.prompt_registry.get(prompt_name, prompt_version)
        if not prompt_def:
            return None

        tv = template_vars or {}
        messages = []
        system = prompt_def.render_system(**tv)
        if system:
            messages.append(LLMMessage(role="system", content=system))
        user = prompt_def.render_user(**tv)
        if user:
            messages.append(LLMMessage(role="user", content=user))

        return LLMRequest(
            task=task or prompt_name,
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            prompt_name=prompt_name,
            prompt_version=prompt_def.version,
        )

    # ── generate ──────────────────────────────────────────────────────────

    async def generate(self, request: LLMRequest) -> LLMResponse:
        cache_key = request.compute_cache_key()
        if cache_key in self._cache:
            cached = self._cache[cache_key]
            return LLMResponse(
                task=cached.task, content=cached.content, model=cached.model,
                usage=cached.usage, latency_ms=cached.latency_ms, cached=True,
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

        if not result.error and backend_name != "mock" and result.model == "mock":
            import warnings
            warnings.warn(f"LLM fallback reached mock for task '{request.task}'; all real backends failed")

        if not result.error:
            self._cache[cache_key] = result

        return result

    async def _call_backend(self, backend_name: str, request: LLMRequest) -> LLMResponse:
        backend = self._backends.get(backend_name)
        if not backend:
            return LLMResponse(
                task=request.task, content="", error=f"backend {backend_name} not found",
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
