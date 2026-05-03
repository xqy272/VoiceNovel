from __future__ import annotations

from pydantic import BaseModel, Field


class SpeechStyle(BaseModel):
    emotion: str = Field(default="neutral")
    intensity: float = Field(default=0.0, ge=0.0, le=1.0)
    prosody_hint: str = Field(default="normal_pause")


class BackendSpeechRequest(BaseModel):
    request_id: str = Field(..., description="unique request id, e.g. ttsreq_ch001_p023_s002_001")
    engine: str = Field(..., description="tts engine: cosyvoice, edge_tts, mock, etc.")
    endpoint: str = Field(default="", description="api endpoint url, empty for local engines")
    segment_id: str = Field(..., description="target segment id")
    voice_id: str = Field(..., description="voice id from voice registry")
    text: str = Field(..., description="final tts text after TTSInputComposer merging")
    style: SpeechStyle = Field(default_factory=SpeechStyle)
    enhancements: list[str] = Field(default_factory=list, description="enhancement ids")
    format: str = Field(default="wav", description="output audio format: wav, mp3")
