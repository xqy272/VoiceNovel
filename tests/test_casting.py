"""Tests for Voice Casting module."""

import pytest

from vn_core.contracts.reading_plan import ReadingPlanEntry, ReadingStyle, VoiceConstraints
from vn_core.store import ProjectStore
from vn_core.voice import VoiceRegistry
from vn_core.voice.casting import cast_all_characters, cast_voice, score_voice


@pytest.fixture
def registry():
    return VoiceRegistry()


class TestVoiceScoring:
    def test_score_narrator_voice(self, registry):
        narrator_voice = registry.get_voice("edge_zh_narrator_001")
        score = score_voice(["narrator", "calm", "neutral"], narrator_voice)
        assert score > 0.0

    def test_score_male_voice(self, registry):
        male_voice = registry.get_voice("edge_zh_male_001")
        score = score_voice(["male", "dialogue"], male_voice)
        assert score > 0.0

    def test_score_zero_for_unapproved(self):
        unapproved = {
            "voice_id": "test_001", "name": "Test", "backend": "mock",
            "type": "builtin", "tags": ["female"], "language": ["zh"],
            "quality": {"overall_quality": 0.5}, "license": "free", "status": "pending",
        }
        score = score_voice(["female"], unapproved)
        assert score == 0.0


class TestCastVoice:
    def test_cast_narrator(self, registry):
        assignment = cast_voice(
            character_id="char_narrator",
            character_traits=["narrator", "neutral", "calm"],
            voice_registry=registry,
        )
        assert assignment.voice_id != ""
        assert assignment.source in ("auto", "fallback")

    def test_cast_male_character(self, registry):
        assignment = cast_voice(
            character_id="char_lu_ming",
            character_traits=["male", "young", "determined"],
            voice_registry=registry,
        )
        assert assignment.voice_id != ""

    def test_cast_with_store(self, tmp_path):
        store = ProjectStore(str(tmp_path / "vc.sqlite"))
        store.initialize()
        assignment = cast_voice(
            character_id="char_lu_ming",
            character_traits=["male", "young"],
            voice_registry=VoiceRegistry(),
            store=store,
            book_id="book01",
        )
        assert assignment.voice_id != ""
        rows = store._get_conn().execute(
            "SELECT voice_id FROM voice_assignments WHERE book_id=? AND character_id=?",
            ("book01", "char_lu_ming"),
        ).fetchone()
        assert rows is not None

    def test_user_locked_preserved(self, tmp_path):
        store = ProjectStore(str(tmp_path / "vc_locked.sqlite"))
        store.initialize()
        store.upsert_voice_assignment(
            "book01", "char_lu_ming",
            "edge_zh_male_001", user_locked=True, source="user",
        )
        assignment = cast_voice(
            character_id="char_lu_ming",
            character_traits=["male", "aggressive"],
            voice_registry=VoiceRegistry(),
            store=store,
            book_id="book01",
        )
        assert assignment.voice_id == "edge_zh_male_001"
        assert assignment.user_locked is True


class TestCastAllCharacters:
    def test_cast_from_plan(self, registry):
        plan = [
            ReadingPlanEntry(
                segment_id="ch001_p001_s000",
                text="\u5929\u7a7a\u5f88\u84dd\u3002",
                speaker_id="char_narrator",
                speaker_confidence=1.0,
                reading_style=ReadingStyle(),
                voice_constraints=VoiceConstraints(gender_style="neutral", tone=["calm"]),
            ),
            ReadingPlanEntry(
                segment_id="ch001_p001_s001",
                text="\u4ed6\u8bf4\u9053\uff1a\u4f60\u597d\u3002",
                speaker_id="char_lu_ming",
                speaker_confidence=0.8,
                reading_style=ReadingStyle(emotion="neutral"),
                voice_constraints=VoiceConstraints(gender_style="male", tone=["determined"]),
            ),
        ]
        assignments = cast_all_characters(plan, registry)
        assert "char_narrator" in assignments
        assert "char_lu_ming" in assignments
