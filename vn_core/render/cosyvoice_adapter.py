"""CosyVoice Docker adapter via OpenAI-compatible /v1/audio/speech endpoint."""

from __future__ import annotations

from pathlib import Path

from vn_core.contracts.speech_request import BackendSpeechRequest
from vn_core.render.result import TTSResult


class CosyVoiceAdapter:
    """TTS adapter for CosyVoice Docker (OpenAI-compatible /v1/audio/speech).

    CosyVoice Docker typically runs at http://localhost:50000 and exposes
    POST /v1/audio/speech with body {model, input, voice, response_format, speed}.
    """

    def __init__(
        self,
        output_dir: str = "data/tts_output",
        endpoint: str = "http://localhost:50000",
        default_voice: str = "default",
        timeout: float = 30.0,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.endpoint = endpoint.rstrip("/")
        self.default_voice = default_voice
        self.timeout = timeout
        self.engine = "cosyvoice"

    async def synthesize(self, request: BackendSpeechRequest) -> TTSResult:
        try:
            import httpx
        except ImportError:
            return TTSResult(
                request_id=request.request_id,
                segment_id=request.segment_id,
                audio_path="",
                engine=self.engine,
                voice_id=request.voice_id,
                status="error",
                error="httpx not installed. Install with: pip install httpx",
            )

        try:
            effective_endpoint = request.endpoint or self.endpoint
            url = f"{effective_endpoint}/v1/audio/speech"
            voice = request.voice_id or self.default_voice
            fmt = request.format or "wav"

            payload = {
                "model": "cosyvoice-v1",
                "input": request.text,
                "voice": voice,
                "response_format": fmt,
                "speed": self._emotion_to_speed(request.style),
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()

            filename = f"{request.segment_id}_cosyvoice.{fmt}"
            filepath = self.output_dir / filename
            filepath.write_bytes(resp.content)

            duration_ms = self._estimate_duration(filepath, request.text)

            return TTSResult(
                request_id=request.request_id,
                segment_id=request.segment_id,
                audio_path=str(filepath),
                duration_ms=duration_ms,
                engine=self.engine,
                voice_id=request.voice_id,
                status="success",
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

    @staticmethod
    def _emotion_to_speed(style) -> float:
        """Map emotion/intensity to CosyVoice speed parameter."""
        if isinstance(style, dict):
            emotion = style.get("emotion", "neutral") or "neutral"
            intensity = style.get("intensity", 0.0) or 0.0
        else:
            emotion = getattr(style, "emotion", "neutral") or "neutral"
            intensity = getattr(style, "intensity", 0.0) or 0.0

        base_speed = {
            "neutral": 1.0,
            "calm": 0.9,
            "sad": 0.85,
            "restrained": 0.95,
            "angry": 1.15,
            "excited": 1.2,
            "curious": 1.05,
            "hesitant": 0.8,
        }.get(emotion, 1.0)

        if intensity > 0.5:
            base_speed += 0.05
        elif intensity > 0.2:
            base_speed += 0.02

        return round(base_speed, 2)

    def _estimate_duration(self, filepath: Path, text: str) -> float:
        """Estimate audio duration from file or fall back to text-length heuristic."""
        try:
            import wave

            with wave.open(str(filepath), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    return (frames / rate) * 1000.0
        except Exception:
            pass

        try:
            import subprocess

            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(filepath)],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip()) * 1000.0
        except Exception:
            pass

        return max(500, len(text) * 100)
