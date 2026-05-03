"""Tests for the Chinese Segmenter module."""

import pytest

from vn_core.segmenter import SEGMENTER_VERSION, ChineseSegmenter


@pytest.fixture
def segmenter():
    return ChineseSegmenter()


class TestBasicSegmentation:
    def test_simple_sentence(self, segmenter):
        segs = segmenter.segment_paragraph("ch001_p001", "他走进了房间。")
        assert len(segs) == 1
        assert segs[0].text == "他走进了房间。"
        assert segs[0].boundary_reason == "sentence_end"
        assert segs[0].segmenter_version == SEGMENTER_VERSION

    def test_multiple_sentences(self, segmenter):
        segs = segmenter.segment_paragraph(
            "ch001_p001",
            "天空很蓝。阳光很暖。微风轻轻吹过。",
        )
        assert len(segs) == 3
        assert segs[0].text == "天空很蓝。"
        assert segs[1].text == "阳光很暖。"
        assert segs[2].text == "微风轻轻吹过。"

    def test_empty_text(self, segmenter):
        segs = segmenter.segment_paragraph("ch001_p001", "")
        assert len(segs) == 0

    def test_whitespace_only(self, segmenter):
        segs = segmenter.segment_paragraph("ch001_p001", "   \n\n  ")
        assert len(segs) == 0

    def test_segment_ids_sequential(self, segmenter):
        segs = segmenter.segment_paragraph(
            "ch001_p001",
            "第一句。第二句。第三句。",
        )
        assert len(segs) == 3
        assert segs[0].segment_id == "ch001_p001_s000"
        assert segs[1].segment_id == "ch001_p001_s001"
        assert segs[2].segment_id == "ch001_p001_s002"

    def test_paragraph_preserves_metadata(self, segmenter):
        segs = segmenter.segment_paragraph(
            "ch002_p005",
            "测试句子。",
            source_href="Text/chapter002.xhtml",
            source_order=5,
        )
        assert segs[0].paragraph_id == "ch002_p005"
        assert segs[0].source_href == "Text/chapter002.xhtml"
        assert segs[0].source_order == 5


class TestDialogueSegmentation:
    def test_simple_dialogue_with_tag(self, segmenter):
        segs = segmenter.segment_paragraph(
            "ch001_p001",
            "\u4ed6\u8bf4\uff1a\u201c\u4f60\u65e2\u7136\u6765\u4e86\u3002\u201d",
        )
        assert len(segs) >= 1
        has_dialogue = any(s.is_dialogue_candidate for s in segs)
        assert has_dialogue

    def test_dialogue_comma_split(self, segmenter):
        segs = segmenter.segment_paragraph(
            "ch001_p001",
            "\u201c\u4f60\u65e2\u7136\u6765\u4e86\uff0c",
        )
        assert len(segs) >= 1
        assert segs[0].is_dialogue_candidate
        assert segs[0].boundary_reason == "comma_inside_quote"

    def test_nested_quotes(self, segmenter):
        segs = segmenter.segment_paragraph(
            "ch001_p001",
            "\u201c\u4ed6\u8bf4\u2018\u4e0d\u53ef\u80fd\u2019\u3002\u201d",
        )
        assert len(segs) >= 1
        has_dialogue = any(s.quote_depth > 0 for s in segs)
        assert has_dialogue

    def test_exclamation_in_quotes(self, segmenter):
        segs = segmenter.segment_paragraph(
            "ch001_p001",
            "\u201c\u5feb\u8dd1\uff01\u201d",
        )
        assert len(segs) >= 1
        assert segs[-1].is_dialogue_candidate


class TestFallbackBehavior:
    def test_very_short_text_not_dropped(self, segmenter):
        segs = segmenter.segment_paragraph("ch001_p001", "\u55ef")
        assert len(segs) == 1
        assert segs[0].text == "嗯"

    def test_dash_em_dash(self, segmenter):
        segs = segmenter.segment_paragraph(
            "ch001_p001",
            "他走了——再也没有回来。",
        )
        assert len(segs) >= 1

    def test_ellipsis(self, segmenter):
        segs = segmenter.segment_paragraph(
            "ch001_p001",
            "她沉默了许久……然后开口了。",
        )
        assert len(segs) >= 1


class TestSegmentStability:
    def test_same_input_same_ids(self, segmenter):
        text = (
            "\u8fd9\u662f\u7b2c\u4e00\u53e5\u8bdd\u3002"
            "\u8fd9\u662f\u7b2c\u4e8c\u53e5\u8bdd\u3002"
        )
        segs1 = segmenter.segment_paragraph("ch001_p001", text)
        segs2 = segmenter.segment_paragraph("ch001_p001", text)
        assert len(segs1) == len(segs2)
        for s1, s2 in zip(segs1, segs2):
            assert s1.segment_id == s2.segment_id

    def test_different_paragraphs_different_ids(self, segmenter):
        segs1 = segmenter.segment_paragraph("ch001_p001", "\u53e5\u5b50\u4e00\u3002")
        segs2 = segmenter.segment_paragraph("ch001_p002", "\u53e5\u5b50\u4e8c\u3002")
        assert segs1[0].segment_id != segs2[0].segment_id
