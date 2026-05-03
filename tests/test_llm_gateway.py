"""Tests for LLM Gateway module."""

import os
from unittest.mock import patch

import pytest

from vn_core.llm_gateway import LLMGateway, LLMMessage, LLMRequest, MockLLMBackend
from vn_core.llm_gateway.backends import (
    AnthropicLLMBackend,
    DeepSeekLLMBackend,
)


@pytest.fixture
def gateway():
    return LLMGateway()


class TestMockLLMBackend:
    @pytest.mark.asyncio
    async def test_mock_speaker_attribution(self):
        backend = MockLLMBackend()
        request = LLMRequest(
            task="speaker_attribution",
            messages=[LLMMessage(role="user", content="test")],
        )
        response = await backend.generate(request)
        assert response.error == ""
        assert response.model == "mock"

    @pytest.mark.asyncio
    async def test_mock_generic(self):
        backend = MockLLMBackend()
        request = LLMRequest(
            task="unknown_task",
            messages=[LLMMessage(role="user", content="test")],
        )
        response = await backend.generate(request)
        assert response.error == ""
        assert "result" in response.content


class TestLLMGateway:
    @pytest.mark.asyncio
    async def test_default_mock_backend(self, gateway):
        request = LLMRequest(
            task="speaker_attribution",
            messages=[LLMMessage(role="user", content="谁在说话？")],
        )
        response = await gateway.generate(request)
        assert response.error == ""
        assert response.model == "mock"

    @pytest.mark.asyncio
    async def test_cache_key_deterministic(self, gateway):
        request1 = LLMRequest(
            task="test",
            messages=[LLMMessage(role="user", content="hello")],
        )
        request2 = LLMRequest(
            task="test",
            messages=[LLMMessage(role="user", content="hello")],
        )
        assert request1.compute_cache_key() == request2.compute_cache_key()

    @pytest.mark.asyncio
    async def test_cache_hit(self, gateway):
        request = LLMRequest(
            task="speaker_attribution",
            messages=[LLMMessage(role="user", content="test cache")],
        )
        await gateway.generate(request)
        response2 = await gateway.generate(request)
        assert response2.cached is True

    @pytest.mark.asyncio
    async def test_clear_cache(self, gateway):
        request = LLMRequest(
            task="test",
            messages=[LLMMessage(role="user", content="clear cache test")],
        )
        await gateway.generate(request)
        gateway.clear_cache()
        assert len(gateway._cache) == 0

    @pytest.mark.asyncio
    async def test_register_custom_backend(self, gateway):
        custom_backend = MockLLMBackend()
        gateway.register_backend("custom", custom_backend, set_default=True)
        request = LLMRequest(
            task="test",
            messages=[LLMMessage(role="user", content="custom backend")],
            model="custom",
        )
        response = await gateway.generate(request)
        assert response.error == ""


class TestDeepSeekBackend:
    def test_construction_defaults(self):
        backend = DeepSeekLLMBackend(api_key="sk-test")
        assert backend.engine == "deepseek"
        assert backend.model == "deepseek-chat"
        assert "api.deepseek.com" in backend.base_url

    def test_missing_api_key_returns_error(self):
        backend = DeepSeekLLMBackend(api_key="")
        request = LLMRequest(
            task="test",
            messages=[LLMMessage(role="user", content="hello")],
        )

        async def _run():
            resp = await backend.generate(request)
            assert resp.error != ""
            assert resp.content == ""

        import asyncio
        asyncio.run(_run())


class TestAnthropicBackend:
    def test_construction_defaults(self):
        backend = AnthropicLLMBackend(api_key="sk-test")
        assert backend.engine == "claude"
        assert "claude" in backend.model

    def test_missing_api_key_returns_error(self):
        backend = AnthropicLLMBackend(api_key="")
        request = LLMRequest(
            task="test",
            messages=[LLMMessage(role="user", content="hello")],
        )

        async def _run():
            resp = await backend.generate(request)
            assert resp.error != ""

        import asyncio
        asyncio.run(_run())


class TestEnvVarConfiguration:
    def test_configure_from_env_openai(self):
        gateway = LLMGateway()
        with patch.dict(os.environ, {
            "VN_LLM_PROVIDER": "openai",
            "VN_LLM_API_KEY": "sk-test",
            "VN_LLM_MODEL": "gpt-4o",
        }):
            gateway.configure_from_env()
        assert gateway._default_backend == "openai"
        assert "openai" in gateway._backends

    def test_configure_from_env_deepseek(self):
        gateway = LLMGateway()
        with patch.dict(os.environ, {
            "VN_LLM_PROVIDER": "deepseek",
            "VN_LLM_API_KEY": "sk-test",
        }):
            gateway.configure_from_env()
        assert gateway._default_backend == "deepseek"
        assert "deepseek" in gateway._backends

    def test_configure_from_env_claude(self):
        gateway = LLMGateway()
        with patch.dict(os.environ, {
            "VN_LLM_PROVIDER": "claude",
            "VN_LLM_API_KEY": "sk-test",
        }):
            gateway.configure_from_env()
        assert gateway._default_backend == "claude"
        assert "claude" in gateway._backends

    def test_configure_from_env_no_provider_noop(self):
        gateway = LLMGateway()
        gateway.configure_from_env()
        assert gateway._default_backend == "mock"

    def test_configure_from_env_custom_base_url(self):
        gateway = LLMGateway()
        with patch.dict(os.environ, {
            "VN_LLM_PROVIDER": "custom_provider",
            "VN_LLM_API_KEY": "sk-test",
            "VN_LLM_BASE_URL": "https://custom.api.com/v1",
        }):
            gateway.configure_from_env()
        assert "custom_provider" in gateway._backends
        assert gateway._default_backend == "custom_provider"

    def test_configure_deepseek_convenience(self):
        gateway = LLMGateway()
        gateway.configure_deepseek(api_key="sk-test")
        assert "deepseek" in gateway._backends
        assert gateway._default_backend == "deepseek"

    def test_configure_claude_convenience(self):
        gateway = LLMGateway()
        gateway.configure_claude(api_key="sk-test")
        assert "claude" in gateway._backends
        assert gateway._default_backend == "claude"
