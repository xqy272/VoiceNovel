# XHTML Generator — AI Agent Guide

## Purpose
Generates cleaned XHTML with data-pid and data-seg-id spans for Reader packages.

## Key Concepts
- Each `<p>` element gets a `data-pid` attribute (paragraph ID)
- Each segment span gets a `data-seg-id` attribute (segment ID)
- The output is valid XHTML suitable for rendering in browser readers
- Source text adaptation is applied before segmentation

## Module: `vn_core/xhtml/`

### `generate_cleaned_html(chapter_id, segments, adapted_texts, source_href) -> str`
1. Group segments by paragraph_id
2. Create `<p data-pid="ch001_p023">` for each paragraph
3. Wrap each segment in `<span data-seg-id="ch001_p023_s002">text</span>`
4. Preserve overall paragraph order from source_order

### HTML Structure
```html
<div class="chapter" data-chapter="ch001">
  <p data-pid="ch001_p001">
    <span data-seg-id="ch001_p001_s000">天空很蓝。</span>
    <span data-seg-id="ch001_p001_s001">阳光温暖。</span>
  </p>
  <p data-pid="ch001_p002">
    <span data-seg-id="ch001_p002_s000">他走了。</span>
  </p>
</div>
```