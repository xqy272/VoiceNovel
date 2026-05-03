"""Tests for LLM Gateway module."""

import pytest

from vn_core.llm_gateway import LLMGateway, LLMMessage, LLMRequest, MockLLMBackend


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
