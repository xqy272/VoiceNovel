"""Tests for Reading Planner module."""

import pytest

from vn_core.contracts.segment import Segment
from vn_core.llm_gateway import LLMGateway
from vn_core.planner import ReadingPlanner


@pytest.fixture
def planner():
    llm = LLMGateway()
    return ReadingPlanner(llm=llm)


def make_segment(pid: str, text: str, is_dialogue: bool = False, order: int = 0) -> Segment:
    return Segment(
        segment_id=f"{pid}_s{order:03d}",
        paragraph_id=pid,
        source_href="",
        source_order=order,
        text=text,
        is_dialogue_candidate=is_dialogue,
        boundary_reason="sentence_end" if "。" in text or "！" in text or "？" in text else "comma",
    )


class TestRuleAttribution:
    @pytest.mark.asyncio
    async def test_narrator_for_non_dialogue(self, planner):
        segments = [make_segment("ch001_p001", "天空很蓝。")]
        plan = await planner.plan_chapter(segments, "ch001")
        assert len(plan) == 1
        assert plan[0].speaker_id == "char_narrator"

    @pytest.mark.asyncio
    async def test_dialogue_with_speaker_tag(self, planner):
        segments = [
            make_segment("ch001_p001", '陆明说："我来了。"', is_dialogue=True),
        ]
        plan = await planner.plan_chapter(segments, "ch001")
        assert len(plan) == 1
        assert plan[0].speaker_candidate is not None
        assert plan[0].speaker_id != "char_narrator"

    @pytest.mark.asyncio
    async def test_simple_quote_detection(self, planner):
        segments = [
            make_segment("ch001_p001", "\u201c\u5feb\u8dd1\uff01\u201d", is_dialogue=True),
        ]
        plan = await planner.plan_chapter(segments, "ch001")
        assert plan[0].speaker_id != "char_narrator" or plan[0].speaker_confidence > 0

    @pytest.mark.asyncio
    async def test_emotion_inference_excited(self, planner):
        segments = [make_segment("ch001_p001", '他喊道："快跑！"', is_dialogue=True)]
        plan = await planner.plan_chapter(segments, "ch001")
        assert plan[0].reading_style.emotion in ("excited", "angry", "neutral")

    @pytest.mark.asyncio
    async def test_narrator_style_neutral(self, planner):
        segments = [make_segment("ch001_p001", "他走了很远的路。")]
        plan = await planner.plan_chapter(segments, "ch001")
        assert plan[0].reading_style.emotion == "neutral"
        assert plan[0].reading_style.intensity == 0.0


class TestCarryForward:
    @pytest.mark.asyncio
    async def test_alternating_dialogue(self, planner):
        segments = [
            make_segment("ch001_p001", "\u9646\u660e\u8d70\u8fdb\u4e86\u623f\u95f4\u3002"),
            make_segment("ch001_p002", "\u201c\u4f60\u597d\uff0c\u201d", is_dialogue=True),
            make_segment("ch001_p003", "\u201c\u4f60\u6765\u4e86\u3002\u201d", is_dialogue=True),
        ]
        plan = await planner.plan_chapter(segments, "ch001")
        assert plan[0].speaker_id == "char_narrator"


class TestExtractSpeaker:
    def test_extract_speaker_with_say(self, planner):
        result = planner._extract_speaker_candidate('陆明说："我来了。"')
        assert result is not None
        assert "陆明" in result

    def test_extract_speaker_no_match(self, planner):
        result = planner._extract_speaker_candidate("天空晴朗如洗。")
        assert result is None

    def test_extract_speaker_with_shout(self, planner):
        result = planner._extract_speaker_candidate('林婉喊道："小心！"')
        assert result is not None


class TestInferVoiceConstraints:
    def test_narrator_constraints(self, planner):
        vc = planner._infer_voice_constraints("char_narrator", False)
        assert vc.gender_style == "neutral"
        assert "calm" in vc.tone

    def test_unknown_character(self, planner):
        vc = planner._infer_voice_constraints("char_lu_ming", True)
        assert vc.gender_style is None
