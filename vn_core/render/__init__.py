"""Speech Gateway: TTS adapter routing, rate limiting, and fallback."""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path

from vn_core.contracts.speech_request import BackendSpeechRequest
from vn_core.render.cosyvoice_adapter import CosyVoiceAdapter as CosyVoiceAdapter
from vn_core.render.result import TTSResult


class MockTTSAdapter:
    def __init__(self, output_dir: str = "data/mock_tts"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.engine = "mock"

    async def synthesize(self, request: BackendSpeechRequest) -> TTSResult:
        await asyncio.sleep(0.01)

        filename = f"{request.segment_id}_{request.engine}.wav"
        filepath = self.output_dir / filename

        duration_ms = max(500, len(request.text) * 100)
        sample_rate = 24000
        frame_count = int(sample_rate * duration_ms / 1000)
        silence = b"\x00\x00" * frame_count
        with wave.open(str(filepath), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(silence)

        return TTSResult(
            request_id=request.request_id,
            segment_id=request.segment_id,
            audio_path=str(filepath),
            duration_ms=duration_ms,
            engine=self.engine,
            voice_id=request.voice_id,
            status="success",
        )


class EdgeTTSAdapter:
    def __init__(self, output_dir: str = "data/tts_output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.engine = "edge_tts"

    async def synthesize(self, request: BackendSpeechRequest) -> TTSResult:
        try:
            import edge_tts

            voice_map = {
                "edge_zh_narrator_001": "zh-CN-XiaoxiaoNeural",
                "edge_zh_male_001": "zh-CN-YunxiNeural",
                "edge_zh_female_001": "zh-CN-XiaoyiNeural",
            }

            edge_voice = voice_map.get(request.voice_id, "zh-CN-XiaoxiaoNeural")

            filename = f"{request.segment_id}_edge.mp3"
            filepath = self.output_dir / filename

            communicate = edge_tts.Communicate(request.text, edge_voice)
            await communicate.save(str(filepath))

            duration_ms = max(500, len(request.text) * 100)

            return TTSResult(
                request_id=request.request_id,
                segment_id=request.segment_id,
                audio_path=str(filepath),
                duration_ms=duration_ms,
                engine=self.engine,
                voice_id=request.voice_id,
                status="success",
            )
        except ImportError:
            return TTSResult(
                request_id=request.request_id,
                segment_id=request.segment_id,
                audio_path="",
                engine=self.engine,
                voice_id=request.voice_id,
                status="error",
                error="edge_tts not installed. Install with: pip install edge-tts",
            )
        except Exception as e:
            return TTSResult(
                request_id=request.request_id,
                segment_id=request.segment_id,
                audio_path="",
                engine=self.engine,
                voice_id=request.voice_id,
                status="error",
                error=str(e),
            )


class SpeechGateway:
    def __init__(self, output_dir: str = "data/tts_output"):
        self.output_dir = output_dir
        self._adapters: dict[str, object] = {}
        self._fallback_order: list[str] = ["cosyvoice", "edge_tts", "mock"]
        self._rate_limits: dict[str, float] = {}
        self._last_call: dict[str, float] = {}

        mock_output = str(Path(output_dir) / "mock")
        tts_output = str(Path(output_dir))

        self._adapters["mock"] = MockTTSAdapter(mock_output)
        self._adapters["edge_tts"] = EdgeTTSAdapter(tts_output)

    def register_adapter(self, engine: str, adapter: object):
        self._adapters[engine] = adapter

    async def synthesize(self, request: BackendSpeechRequest) -> TTSResult:
        engine = request.engine

        if engine in self._adapters:
            result = await self._adapters[engine].synthesize(request)
            if result.status == "success":
                return result

        for fallback_engine in self._fallback_order:
            if fallback_engine == engine:
                continue
            if fallback_engine not in self._adapters:
                continue

            fallback_request = BackendSpeechRequest(
                request_id=request.request_id + f"_fb_{fallback_engine}",
                engine=fallback_engine,
                endpoint="",
                segment_id=request.segment_id,
                voice_id=request.voice_id,
                text=request.text,
                style=request.style,
                enhancements=request.enhancements,
                format=request.format,
            )
            result = await self._adapters[fallback_engine].synthesize(fallback_request)
            if result.status == "success":
                return result

        return TTSResult(
            request_id=request.request_id,
            segment_id=request.segment_id,
            audio_path="",
            engine=engine,
            voice_id=request.voice_id,
            status="error",
            error=f"All TTS backends failed for segment {request.segment_id}",
        )
