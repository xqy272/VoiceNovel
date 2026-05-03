"""TTS Input Composer: merge text, style, voice,
and backend capabilities into BackendSpeechRequest."""

from __future__ import annotations

from vn_core.contracts.speech_request import BackendSpeechRequest, SpeechStyle


class TTSInputComposer:
    def compose(
        self,
        segment_id: str,
        tts_base_text: str,
        voice_id: str,
        engine: str,
        endpoint: str = "",
        reading_style: dict | None = None,
        prosody_hint: str = "normal_pause",
        enhancements: list[str] | None = None,
        format: str = "wav",
    ) -> BackendSpeechRequest:
        style = SpeechStyle(
            emotion=(reading_style or {}).get("emotion", "neutral"),
            intensity=(reading_style or {}).get("intensity", 0.0),
            prosody_hint=prosody_hint or "normal_pause",
        )

        return BackendSpeechRequest(
            request_id=f"ttsreq_{segment_id}_001",
            engine=engine,
            endpoint=endpoint,
            segment_id=segment_id,
            voice_id=voice_id,
            text=tts_base_text,
            style=style,
            enhancements=enhancements or [],
            format=format,
        )
