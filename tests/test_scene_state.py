"""Tests for SceneStateExtractor and rich scene snapshots."""

from __future__ import annotations

from vn_core.contracts.reading_plan import ReadingPlanEntry, ReadingStyle
from vn_core.scene_state import extract_from_plan, merge_with_existing


def _make_entry(segment_id, speaker_id, emotion="neutral"):
    return ReadingPlanEntry(
        segment_id=segment_id,
        text="test",
        speaker_id=speaker_id,
        reading_style=ReadingStyle(emotion=emotion),
    )


class TestSceneStateExtractor:
    def test_empty_plan(self):
        state = extract_from_plan([])
        assert state["segment_count"] == 0
        assert state["dialogue_density"] == 0.0
        assert state["turn_pattern"] == "none"

    def test_all_narrator(self):
        plan = [_make_entry(f"s{i:03d}", "char_narrator") for i in range(10)]
        state = extract_from_plan(plan)
        assert state["narrator_ratio"] == 1.0
        assert state["dialogue_density"] == 0.0
        assert state["turn_pattern"] == "none"

    def test_alternating_two_characters(self):
        plan = [
            _make_entry("s001", "char_lu_ming"),
            _make_entry("s002", "char_lin_wan"),
            _make_entry("s003", "char_lu_ming"),
            _make_entry("s004", "char_lin_wan"),
            _make_entry("s005", "char_lu_ming"),
        ]
        state = extract_from_plan(plan)
        assert state["turn_pattern"] == "alternating"
        assert state["last_speaker"] == "char_lu_ming"
        assert state["last_addressee"] == "char_lin_wan"
        assert state["character_turn_counts"]["char_lu_ming"] == 3
        assert state["character_turn_counts"]["char_lin_wan"] == 2

    def test_monologue(self):
        plan = [_make_entry(f"s{i:03d}", "char_lu_ming") for i in range(5)]
        state = extract_from_plan(plan)
        assert state["turn_pattern"] == "monologue"
        assert state["last_speaker"] == "char_lu_ming"

    def test_emotional_arc_sampling(self):
        plan = []
        for i in range(100):
            emo = "excited" if i < 50 else "calm"
            plan.append(_make_entry(f"s{i:03d}", "char_narrator", emo))
        state = extract_from_plan(plan)
        assert len(state["emotional_arc"]) > 0

    def test_merge_preserves_existing_fields(self):
        existing = {"summary": "old summary", "location": "客栈"}
        new = {"last_speaker": "char_lu_ming", "dialogue_density": 0.5}
        merged = merge_with_existing(existing, new)
        assert merged["summary"] == "old summary"
        assert merged["location"] == "客栈"
        assert merged["last_speaker"] == "char_lu_ming"
        assert merged["dialogue_density"] == 0.5

    def test_merge_with_none(self):
        new = {"last_speaker": "char_lu_ming"}
        merged = merge_with_existing(None, new)
        assert merged == new
