"""Voice Registry and lifecycle management."""


FALLBACK_VOICES = {
    "narrator": "edge_zh_narrator_001",
    "male_dialogue": "edge_zh_male_001",
    "female_dialogue": "edge_zh_female_001",
    "unknown_dialogue": "edge_zh_narrator_001",
    "fallback": "edge_zh_narrator_001",
}


BUILTIN_VOICES = [
    {
        "voice_id": "edge_zh_narrator_001",
        "name": "中文女声旁白",
        "backend": "edge_tts",
        "type": "builtin",
        "tags": ["female", "adult", "narrator", "calm"],
        "language": ["zh"],
        "quality": {"technical_quality": 0.75, "overall_quality": 0.75},
        "license": "free",
        "status": "approved",
    },
    {
        "voice_id": "edge_zh_male_001",
        "name": "中文男声对话",
        "backend": "edge_tts",
        "type": "builtin",
        "tags": ["male", "adult", "dialogue"],
        "language": ["zh"],
        "quality": {"technical_quality": 0.75, "overall_quality": 0.75},
        "license": "free",
        "status": "approved",
    },
    {
        "voice_id": "edge_zh_female_001",
        "name": "中文女声对话",
        "backend": "edge_tts",
        "type": "builtin",
        "tags": ["female", "adult", "dialogue"],
        "language": ["zh"],
        "quality": {"technical_quality": 0.75, "overall_quality": 0.75},
        "license": "free",
        "status": "approved",
    },
    {
        "voice_id": "mock_tts_001",
        "name": "Mock TTS (silent)",
        "backend": "mock",
        "type": "builtin",
        "tags": ["mock", "test"],
        "language": ["zh"],
        "quality": {"technical_quality": 0.0, "overall_quality": 0.0},
        "license": "internal",
        "status": "approved",
    },
]


class VoiceRegistry:
    def __init__(self):
        self._voices: dict[str, dict] = {}
        for v in BUILTIN_VOICES:
            self._voices[v["voice_id"]] = v

    def get_voice(self, voice_id: str) -> dict | None:
        return self._voices.get(voice_id)

    def list_voices(self, backend: str | None = None, status: str | None = None) -> list[dict]:
        voices = list(self._voices.values())
        if backend:
            voices = [v for v in voices if v["backend"] == backend]
        if status:
            voices = [v for v in voices if v["status"] == status]
        return voices

    def register_voice(self, voice_config: dict):
        voice_id = voice_config["voice_id"]
        self._voices[voice_id] = voice_config

    def find_matching_voices(self, tags: list[str], language: str = "zh") -> list[dict]:
        matches = []
        for v in self._voices.values():
            if v.get("status") != "approved":
                continue
            if language not in v.get("language", []):
                continue
            voice_tags = set(v.get("tags", []))
            overlap = len(set(tags) & voice_tags)
            if overlap > 0:
                matches.append((overlap, v))
        matches.sort(key=lambda x: x[0], reverse=True)
        return [m[1] for m in matches]

    def get_fallback_voice(self, role: str = "fallback") -> str:
        return FALLBACK_VOICES.get(role, FALLBACK_VOICES["fallback"])
