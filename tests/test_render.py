"""Tests for Speech Gateway and TTS adapters."""

import wave

import pytest

from vn_core.contracts.speech_request import BackendSpeechRequest, SpeechStyle
from vn_core.render import CosyVoiceAdapter, MockTTSAdapter, SpeechGateway


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


class TestCosyVoiceAdapter:
    def test_emotion_to_speed_mapping(self):
        """Verify emotion-to-speed mapping for CosyVoice."""
        adapter = CosyVoiceAdapter(output_dir="data/test_tts")

        neutral = type("Style", (), {"emotion": "neutral", "intensity": 0.0})()
        assert adapter._emotion_to_speed(neutral) == 1.0

        excited = type("Style", (), {"emotion": "excited", "intensity": 0.8})()
        assert adapter._emotion_to_speed(excited) == 1.25

        sad = type("Style", (), {"emotion": "sad", "intensity": 0.0})()
        assert adapter._emotion_to_speed(sad) == 0.85

    def test_emotion_to_speed_unknown_defaults_to_neutral(self):
        adapter = CosyVoiceAdapter(output_dir="data/test_tts")
        unknown = type("Style", (), {"emotion": "unknown_emotion", "intensity": 0.0})()
        assert adapter._emotion_to_speed(unknown) == 1.0

    def test_construction_defaults(self):
        adapter = CosyVoiceAdapter(output_dir="data/test_tts")
        assert adapter.engine == "cosyvoice"
        assert adapter.endpoint == "http://localhost:50000"
        assert adapter.default_voice == "default"

    @pytest.mark.asyncio
    async def test_synthesize_no_backend_available(self):
        """When CosyVoice isn't running, should return error (never raise)."""
        adapter = CosyVoiceAdapter(output_dir="data/test_tts", endpoint="http://127.0.0.1:1")
        request = BackendSpeechRequest(
            request_id="ttsreq_cosy_test",
            engine="cosyvoice",
            segment_id="ch001_p001_s000",
            voice_id="default",
            text="测试文本",
            style=SpeechStyle(),
        )
        result = await adapter.synthesize(request)
        assert result.status == 'error'  # server not running, must not raise


class TestCosyVoiceGatewayIntegration:
    def test_cosyvoice_in_fallback_chain(self):
        """Ensure cosyvoice is in SpeechGateway fallback order."""
        gateway = SpeechGateway(output_dir="data/test_tts")
        assert "cosyvoice" in gateway._fallback_order
        assert gateway._fallback_order[0] == "cosyvoice"

    def test_register_cosyvoice_adapter(self):
        gateway = SpeechGateway(output_dir="data/test_tts")
        adapter = CosyVoiceAdapter(output_dir="data/test_tts")
        gateway.register_adapter("cosyvoice", adapter)
        assert "cosyvoice" in gateway._adapters
        assert gateway._adapters["cosyvoice"] is adapter


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
