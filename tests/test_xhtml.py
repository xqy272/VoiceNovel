"""Tests for XSS Generator module."""

from vn_core.contracts.segment import Segment
from vn_core.xhtml import generate_cleaned_html, wrap_full_document


def make_seg(pid: str, text: str, order: int = 0) -> Segment:
    return Segment(
        segment_id=f"{pid}_s{order:03d}",
        paragraph_id=pid,
        source_href="",
        source_order=order,
        text=text,
    )


class TestXHTMLGenerator:
    def test_basic_html(self):
        segments = [
            make_seg("ch001_p001", "\u5929\u7a7a\u5f88\u84dd\u3002", 0),
            make_seg("ch001_p001", "\u9633\u5149\u6696\u6696\u3002", 1),
        ]
        html = generate_cleaned_html("ch001", segments)
        assert 'data-chapter="ch001"' in html
        assert 'data-pid="ch001_p001"' in html
        assert 'data-seg-id="ch001_p001_s000"' in html
        assert 'data-seg-id="ch001_p001_s001"' in html

    def test_multi_paragraph(self):
        segments = [
            make_seg("ch001_p001", "\u7b2c\u4e00\u6bb5\u3002", 0),
            make_seg("ch001_p002", "\u7b2c\u4e8c\u6bb5\u3002", 0),
        ]
        html = generate_cleaned_html("ch001", segments)
        assert 'data-pid="ch001_p001"' in html
        assert 'data-pid="ch001_p002"' in html

    def test_adapted_text_override(self):
        segments = [make_seg("ch001_p001", "\u539f\u6587", 0)]
        adapted = {"ch001_p001_s000": "\u4fee\u6539\u540e"}
        html = generate_cleaned_html("ch001", segments, adapted_texts=adapted)
        assert "\u4fee\u6539\u540e" in html
        assert "\u539f\u6587" not in html

    def test_full_document(self):
        body = '<div class="chapter">Hello</div>'
        doc = wrap_full_document(body, book_id="book01", title="Test Book")
        assert "VoiceNovel" in doc
        assert "Test Book" in doc
        assert "utf-8" in doc

    def test_html_escaping(self):
        segments = [make_seg("p001", "He said <hello> & 'good'", 0)]
        html = generate_cleaned_html("ch001", segments)
        assert "&lt;" in html or "&amp;" in html
