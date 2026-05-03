"""Tests for Speech Gateway and TTS adapters."""

import wave

import pytest

from vn_core.contracts.speech_request import BackendSpeechRequest, SpeechStyle
from vn_core.render import MockTTSAdapter, SpeechGateway


@pytest.fixture
def gateway():
    return SpeechGateway(output_dir="data/test_tts")


class TestMockTTSAdapter:
    @pytest.mark.asyncio
    async def test_synthesize(self):
        adapter = MockTTSAdapter(output_dir="data/test_mock_tts")
        request = BackendSpeechRequest(
            request_id="ttsreq_test_001",
            engine="mock",
            segment_id="ch001_p001_s000",
            voice_id="mock_tts_001",
            text="测试文本",
            style=SpeechStyle(),
        )
        result = await adapter.synthesize(request)
        assert result.status == "success"
        assert result.engine == "mock"
        assert result.duration_ms > 0
        with wave.open(result.audio_path, "rb") as wav:
            assert wav.getnchannels() == 1
            assert wav.getframerate() > 0
            assert wav.getnframes() > 0


class TestSpeechGateway:
    @pytest.mark.asyncio
    async def test_mock_synthesize(self, gateway):
        request = BackendSpeechRequest(
            request_id="ttsreq_gw_001",
            engine="mock",
            segment_id="ch001_p001_s000",
            voice_id="mock_tts_001",
            text="网关测试文本",
            style=SpeechStyle(),
        )
        result = await gateway.synthesize(request)
        assert result.status == "success"

    @pytest.mark.asyncio
    async def test_fallback_on_unknown_engine(self, gateway):
        request = BackendSpeechRequest(
            request_id="ttsreq_gw_002",
            engine="nonexistent_engine",
            segment_id="ch001_p001_s000",
            voice_id="mock_tts_001",
            text="回退测试文本",
            style=SpeechStyle(),
        )
        result = await gateway.synthesize(request)
        assert result.status == "success"
        assert result.engine in ("mock", "edge_tts")


class TestTTSInputComposer:
    def test_compose_basic(self):
        from vn_core.render.tts_input_composer import TTSInputComposer

        composer = TTSInputComposer()
        request = composer.compose(
            segment_id="ch001_p001_s000",
            tts_base_text="他说：你好。",
            voice_id="edge_zh_narrator_001",
            engine="edge_tts",
        )
        assert request.segment_id == "ch001_p001_s000"
        assert request.text == "他说：你好。"
        assert request.engine == "edge_tts"
        assert request.voice_id == "edge_zh_narrator_001"

    def test_compose_with_style(self):
        from vn_core.render.tts_input_composer import TTSInputComposer

        composer = TTSInputComposer()
        request = composer.compose(
            segment_id="ch001_p001_s000",
            tts_base_text="紧急消息！",
            voice_id="edge_zh_male_001",
            engine="edge_tts",
            reading_style={"emotion": "excited", "intensity": 0.8},
            prosody_hint="short_pause",
        )
        assert request.style.emotion == "excited"
        assert request.style.intensity == 0.8
        assert request.style.prosody_hint == "short_pause"
