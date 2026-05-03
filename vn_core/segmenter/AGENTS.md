# Segmenter — AI Agent Guide

## Purpose
Rule-based Chinese sentence/clause splitting with stable `segment_id` generation. Produces `Segment` objects with quote-depth tracking and dialogue candidate flags.

## Key Concepts
- **Stable IDs**: Once `segmenter_version` (`zh_clause_v1`) is locked, segment IDs never change for the same input
- **Quote-aware splitting**: Tracks Chinese quotation marks (`「」` `""`) depth; splits on commas inside quotes, sentence-end outside
- **Boundary reasons**: Each segment carries metadata about why the split occurred (sentence_end, comma_inside_quote, newline_break, etc.)
- **Short segment merging**: Segments under 2 chars get merged with neighbors unless they're dialogue

## Module: `vn_core/segmenter/`

### `ChineseSegmenter(version="zh_clause_v1")`

#### `segment_paragraph(paragraph_id, text, source_href, source_order) -> list[Segment]`
Main entry point. Returns 0+ segments per paragraph.

#### `segment_chapter(chapter_id, paragraphs) -> list[Segment]`
Batch-process all paragraphs in a chapter.

### Splitting Rules (in order)
1. **Quote tracking**: `「` / `"` push depth; `」` / `"` pop depth
2. **Inside quotes**: Split on `，：；` (Chinese commas/colons)
3. **Outside quotes**: Split on `。！？…` (sentence end)
4. **Dash breaks**: `——` triggers a split
5. **Newlines**: Always split boundaries
6. **Post-merge**: Adjacent short non-dialogue segments merged (min 2 chars)

### Global Constant
- `SEGMENTER_VERSION = "zh_clause_v1"` — Used across the pipeline for provenance

## Dependencies
- `vn_core.contracts.segment.Segment` — output model
