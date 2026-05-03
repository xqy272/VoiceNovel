# Reading Planner — AI Agent Guide

## Purpose
Per-segment speaker attribution, reading style inference, and voice constraint generation. Uses rule-based heuristics by default, with optional LLM-based attribution for dialogue segments.

## Key Concepts
- **Dual attribution**: Rule-based fast path for all segments; LLM path for dialogue when real LLM backend is configured
- **Carry-forward**: Low-confidence speakers inherit from the previous dialogue speaker
- **Voice constraints**: Gender, tone tags, and age traits are inferred per speaker for downstream voice casting
- **Narrator fallback**: `char_narrator` is the universal fallback speaker ID

## Module: `vn_core/planner/`

### `ReadingPlanner(llm, book_model)`

#### `plan_chapter(segments, chapter_id, scene_context) -> list[ReadingPlanEntry]`
Main entry point. Processes all segments sequentially:
1. For each segment, extract speaker candidate via regex
2. If dialogue + real LLM: use `_llm_attribution`
3. Otherwise: use `_rule_attribution`
4. Run `_carry_forward_speakers` pass over the plan

### Speaker Extraction Patterns
- `"XXX说/喊/叫/道..."` — speaker tag before dialogue
- `XXX说/喊道： "..."` — speaker tag with colon before quote
- `XXX说/问/笑道：` — speaker tag with colon (no quote required)

### Rule Attribution Logic
- Non-dialogue → narrator with confidence 1.0
- Dialogue with matched character in BookModel → confidence 0.85
- Dialogue with unmatched name → confidence 0.6
- Dialogue with no speaker candidate → confidence 0.3-0.4 (carry-forward)

### Reading Style Inference
- `！` → excited, intensity 0.7
- `？` → curious, intensity 0.3
- `……` → hesitant, long_pause
- Dialogue adds +0.2 intensity

## Dependencies
- `vn_core.contracts.reading_plan` — ReadingPlanEntry, ReadingStyle, Enhancements, VoiceConstraints
- `vn_core.contracts.segment` — Segment
- `vn_core.llm_gateway` — LLMGateway, LLMMessage, LLMRequest
- `vn_core.book_model` — BookModel (optional, for character lookup)
