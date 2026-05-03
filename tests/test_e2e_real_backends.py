"""E2E integration tests requiring real TTS and/or LLM backends.

These tests are SKIPPED by default.  Opt in with::

    pytest tests/test_e2e_real_backends.py --real-backends

Environment variables control which backends are used:

    VN_LLM_PROVIDER   = openai | deepseek | claude
    VN_LLM_API_KEY    = sk-...
    VN_LLM_MODEL      = gpt-4o-mini | deepseek-chat | claude-sonnet-4-6
    VN_TTS_ENGINE     = edge_tts | cosyvoice
    VN_COSYVOICE_ENDPOINT = http://localhost:50000  (for cosyvoice)
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from vn_core.contracts.speech_request import BackendSpeechRequest, SpeechStyle
from vn_core.importers import import_book
from vn_core.llm_gateway import LLMGateway, LLMMessage, LLMRequest
from vn_core.pipeline.pipeline import Pipeline
from vn_core.render import CosyVoiceAdapter
from vn_core.store import ProjectStore

# ── helpers ─────────────────────────────────────────────────────────────────

def _audio_has_content(path: str) -> bool:
    """Check that a WAV file is not silent (has non-zero samples)."""
    with wave.open(path, "rb") as wf:
        data = wf.readframes(wf.getnframes())
        # Check for any non-zero bytes (real audio)
        return any(b != 0 for b in data[:10000])


# ── real TTS tests ──────────────────────────────────────────────────────────

@pytest.mark.real_tts
class TestRealTTSBackend:
    @pytest.mark.asyncio
    async def test_cosyvoice_produces_audible_audio(self):
        """Verify CosyVoice adapter produces non-silent WAV when server is running."""
        adapter = CosyVoiceAdapter(output_dir="data/test_real_tts")
        request = BackendSpeechRequest(
            request_id="ttsreq_real_001",
            engine="cosyvoice",
            segment_id="ch001_p001_s000",
            voice_id="default",
            text="你好世界，这是一段测试文本。",
            style=SpeechStyle(),
            format="wav",
        )
        result = await adapter.synthesize(request)
        assert result.status == "success", f"CosyVoice failed: {result.error}"
        assert result.duration_ms > 0
        assert _audio_has_content(result.audio_path), "Audio is silent"

    @pytest.mark.asyncio
    async def test_cosyvoice_handles_empty_text(self):
        """CosyVoice should handle empty text gracefully."""
        adapter = CosyVoiceAdapter(output_dir="data/test_real_tts")
        request = BackendSpeechRequest(
            request_id="ttsreq_real_empty",
            engine="cosyvoice",
            segment_id="ch001_p001_s000",
            voice_id="default",
            text="。",
            style=SpeechStyle(),
        )
        result = await adapter.synthesize(request)
        assert result.status in ("success", "error")
        if result.status == "error":
            assert len(result.error) > 0


# ── real LLM tests ──────────────────────────────────────────────────────────

@pytest.mark.real_llm
class TestRealLLMBackend:
    @pytest.mark.asyncio
    async def test_real_llm_produces_valid_speaker_json(self):
        """Verify real LLM produces parseable speaker attribution JSON."""

        gateway = LLMGateway()
        gateway.configure_from_env()

        request = LLMRequest(
            task="speaker_attribution",
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "You are analyzing a Chinese novel. Identify the speaker. "
                        "Output JSON with speaker_candidate, speaker_id, "
                        "speaker_confidence, reading_style, and evidence."
                    ),
                ),
                LLMMessage(
                    role="user",
                    content='陆明冷冷道："你既然来了，就别想走。"',
                ),
            ],
            temperature=0.1,
            max_tokens=512,
        )
        response = await gateway.generate(request)
        assert not response.error, f"LLM error: {response.error}"
        assert response.content, "Empty response"
        assert response.latency_ms > 0

        try:
            data = json.loads(response.content)
            assert "speaker_id" in data or "speaker_candidate" in data
        except json.JSONDecodeError:
            pytest.fail(f"LLM didn't return valid JSON: {response.content[:200]}")

    @pytest.mark.asyncio
    async def test_real_llm_character_extraction(self):
        """Verify real LLM can extract characters from a novel passage."""

        gateway = LLMGateway()
        gateway.configure_from_env()

        text = """陆明推门走进客栈，目光扫过堂内的客人。掌柜的迎上来笑道："客官可是要住店？"
"一间上房。"陆明淡淡说道。
这时，一个身着青衣的女子从楼梯上走下来，正是林晚。
"少主，您终于来了。"林晚行了一礼。"""

        request = LLMRequest(
            task="character_extraction",
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "Extract characters from the Chinese novel text. "
                        "Output JSON with characters and glossary arrays."
                    ),
                ),
                LLMMessage(role="user", content=text),
            ],
            temperature=0.1,
            max_tokens=1024,
        )
        response = await gateway.generate(request)
        assert not response.error, f"LLM error: {response.error}"
        assert response.content
        try:
            data = json.loads(response.content)
            assert "characters" in data
            assert len(data["characters"]) >= 1
        except json.JSONDecodeError:
            pytest.fail(f"LLM didn't return valid JSON: {response.content[:200]}")


# ── full pipeline E2E with real backends ────────────────────────────────────

@pytest.mark.real_tts
@pytest.mark.real_llm
class TestFullPipelineRealBackends:
    @pytest.mark.asyncio
    async def test_cold_start_with_real_backends_produces_audio(self, tmp_path):
        """Cold-start the golden book with real LLM + real TTS, verify audible output."""
        import os

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        store = ProjectStore(str(data_dir / "projects.sqlite"))

        # Import golden test book
        src = Path("tests/golden_books/mountain_inn.txt")
        if not src.exists():
            pytest.skip("golden book not found")
        import_book(str(src), book_id="demo_real", store=store)

        # Set up real LLM gateway
        llm = LLMGateway()
        llm.configure_from_env()

        if llm._default_backend == "mock":
            pytest.skip("no real LLM backend configured (set VN_LLM_API_KEY)")

        # Set up pipeline with real TTS engine
        tts_engine = os.environ.get("VN_TTS_ENGINE", "edge_tts")
        pipeline = Pipeline(
            store=store,
            llm=llm,
            output_dir=str(data_dir),
            tts_engine=tts_engine,
            audio_codec="wav",  # WAV for easier verification in tests
        )

        # Cold start
        result = await pipeline.cold_start(
            source_path=str(src),
            book_id="demo_real",
        )
        assert result.phase, f"Cold start failed: {result.errors}"

        # Verify buffer package exists
        packages_dir = Path(pipeline.output_dir) / "packages" / "demo_real"
        package_dirs = list(packages_dir.glob("*buffer*"))
        if not package_dirs:
            package_dirs = list(packages_dir.glob("ch0*"))

        if package_dirs:
            pkg = package_dirs[0]
            manifest_path = pkg / "manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text())
                assert manifest.get("book_id") == "demo_real"
                audio_codec = manifest.get("audio_codec", "wav")
                audio_file = pkg / "audio" / f"{pkg.name}.{audio_codec}"
                if audio_file.exists():
                    if audio_codec == "wav":
                        assert _audio_has_content(str(audio_file)), \
                            f"Audio is silent: {audio_file} ({audio_file.stat().st_size} bytes)"
        else:
            pytest.fail(
                f"No package dirs found under {packages_dir} "
                f"(contents: {list(packages_dir.iterdir())})"
            )
