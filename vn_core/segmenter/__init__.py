"""Chinese Segmenter: rule-based sentence/clause splitting for Chinese fiction."""

from __future__ import annotations

from vn_core.contracts.segment import Segment

SEGMENTER_VERSION = "zh_clause_v1"


class ChineseSegmenter:
    def __init__(self, version: str = SEGMENTER_VERSION):
        self.version = version

    def segment_paragraph(
        self,
        paragraph_id: str,
        text: str,
        source_href: str = "",
        source_order: int = 0,
        source_dom_hint: str = "",
    ) -> list[Segment]:
        if not text.strip():
            return []

        segments = self._split_text(
            text, paragraph_id, source_href, source_order, source_dom_hint,
        )
        return segments

    def segment_chapter(
        self,
        chapter_id: str,
        paragraphs: list[tuple[str, str, str, int, str]],
    ) -> list[Segment]:
        all_segments: list[Segment] = []
        for pid, text, href, order, dom_hint in paragraphs:
            segs = self.segment_paragraph(pid, text, href, order, dom_hint)

            all_segments.extend(segs)
        return all_segments

    def _split_text(
        self,
        text: str,
        paragraph_id: str,
        source_href: str,
        source_order: int,
        source_dom_hint: str = "",
    ) -> list[Segment]:
        segments: list[Segment] = []
        quotes = list(self._find_quote_spans(text))

        raw_splits = self._rule_based_split(text, quotes)

        for idx, (chunk, boundary_reason, quote_depth, is_dialogue) in enumerate(raw_splits):
            if not chunk.strip():
                continue
            seg_id = f"{paragraph_id}_s{idx:03d}"
            segments.append(
                Segment(
                    segment_id=seg_id,
                    segmenter_version=self.version,
                    paragraph_id=paragraph_id,
                    source_href=source_href,
                    source_order=source_order,
                    source_dom_hint=source_dom_hint,
                    text=chunk.strip(),
                    quote_depth=quote_depth,
                    is_dialogue_candidate=is_dialogue,
                    boundary_reason=boundary_reason,
                )
            )

        self._fix_segment_indices(segments, paragraph_id)
        return segments

    @staticmethod
    def _find_quote_spans(text: str):
        stack: list[tuple[int, int]] = []
        open_quotes = "\u201c\u300c\u2018"
        close_quotes = "\u201d\u300d\u2019"
        for i, ch in enumerate(text):
            if ch in open_quotes:
                stack.append((i, 1))
            elif ch in close_quotes:
                if stack:
                    start, depth = stack.pop()
                    yield (start, i, depth + 1)

    def _rule_based_split(self, text: str, quote_spans) -> list[tuple[str, str, int, bool]]:
        result: list[tuple[str, str, int, bool]] = []

        in_quote = False
        quote_depth = 0
        current = ""
        i = 0

        while i < len(text):
            ch = text[i]

            if ch in "\u201c\u300c\u2018":
                if current.strip():
                    result.append((current, "boundary_before_quote", quote_depth, False))
                    current = ""
                in_quote = True
                quote_depth += 1
                current += ch
                i += 1
                continue

            if ch in "\u201d\u300d\u2019":
                current += ch
                quote_depth = max(0, quote_depth - 1)
                if quote_depth == 0:
                    in_quote = False
                    result.append((current, "boundary_after_quote", quote_depth, True))
                    current = ""
                    i += 1
                    continue
                i += 1
                continue

            if in_quote and ch in "\uff0c\uff1a\uff1b":
                current += ch
                result.append((current, "comma_inside_quote", quote_depth, True))
                current = ""
                i += 1
                continue

            if not in_quote and ch in "\u3002\uff01\uff1f\u2026":
                current += ch
                result.append((current, "sentence_end", quote_depth, False))
                current = ""
                i += 1
                continue

            if ch == "\u2014" and i + 1 < len(text) and text[i + 1] == "\u2014":
                if current.strip():
                    current += "\u2014\u2014"
                    result.append((current, "dash_break", quote_depth, False))
                    current = ""
                else:
                    current += "\u2014\u2014"
                i += 2
                continue

            if ch == "\n":
                if current.strip():
                    result.append((current, "newline_break", quote_depth, False))
                    current = ""
                i += 1
                continue

            current += ch
            i += 1

        if current.strip():
            result.append((current, "end_of_paragraph", quote_depth, in_quote))

        return self._merge_short_segments(result)

    @staticmethod
    def _merge_short_segments(
        segments: list[tuple[str, str, int, bool]],
        min_length: int = 2,
    ) -> list[tuple[str, str, int, bool]]:
        if not segments:
            return segments

        merged: list[tuple[str, str, int, bool]] = []
        current = segments[0]

        for seg in segments[1:]:
            cur_text = current[0].strip()

            if len(cur_text) < min_length and not current[3]:
                merged_text = current[0] + seg[0]
                current = (
                    merged_text,
                    current[1],
                    current[2],
                    current[3] or seg[3],
                )
            else:
                merged.append(current)
                current = seg

        merged.append(current)
        return merged

    @staticmethod
    def _fix_segment_indices(segments: list[Segment], paragraph_id: str):
        for i, seg in enumerate(segments):
            seg.segment_id = f"{paragraph_id}_s{i:03d}"
