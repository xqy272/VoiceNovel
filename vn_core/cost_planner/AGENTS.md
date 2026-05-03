# Cost Planner — AI Agent Guide

## Purpose
Token and audio duration cost estimation with configurable provider rate cards. Provides pre-run estimates (for user decision-making) and post-run actuals (for cost tracking).

## Key Concepts
- **Rate cards**: Per-provider USD rates for LLM (per 1M tokens) and TTS (per 1M chars)
- **Estimate vs actual**: `estimate_type="pre_run"` uses heuristics; `"post_run"` uses real usage data
- **Faithful mode**: Zero LLM cost since no LLM calls are made

## Module: `vn_core/cost_planner/`

### Rate Cards
```python
LLM_RATES = {
    "gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60},
    "gpt-4o":        {"input_per_1m": 2.50, "output_per_1m": 10.00},
    "claude-haiku":  {"input_per_1m": 0.25, "output_per_1m": 1.25},
    "claude-sonnet": {"input_per_1m": 3.00, "output_per_1m": 15.00},
    "deepseek-chat": {"input_per_1m": 0.27, "output_per_1m": 1.10},
    "mock":          {"input_per_1m": 0.0,  "output_per_1m": 0.0},
}
TTS_RATES = {"edge_tts": 0.0, "mock": 0.0, "cosyvoice": 0.0, "openai_tts": 15.00, "azure_tts": 15.00}
```

### Data Types
- `LLMCostLine` — Per-call LLM cost: model, task, input/output tokens, cost, cached flag
- `TTSCostLine` — Per-batch TTS cost: engine, chars, duration, cost
- `CostEstimate` — Aggregate estimate: book/chapter, pre/post run, LLM + TTS totals

### `CostPlanner(llm_rates, tts_rates)`

#### `estimate_llm_cost(model, task, input_tokens, output_tokens, segment_count, chapter_count) -> LLMCostLine`
If token counts are 0, uses heuristics based on task type and segment/chapter counts.

#### `estimate_llm_cost_from_response(model, task, usage, cached) -> LLMCostLine`
Compute actual cost from LLM response usage dict.

#### `estimate_tts_cost(engine, total_chars, total_duration_ms, segment_count, avg_chars_per_segment) -> TTSCostLine`
If char/duration counts are 0, estimates from segment count.

#### `estimate_chapter(book_id, chapter_id, segment_count, llm_model, tts_engine, reading_profile) -> CostEstimate`
Pre-run estimate for one chapter. Includes LLM tasks (character_extraction + speaker_attribution) and TTS.

#### `estimate_book(book_id, chapter_ids, total_segments, ...) -> CostEstimate`
Pre-run estimate for an entire book by summing per-chapter estimates.

### Heuristics
- Input tokens: `500 + chapter_count * 1200` (character_extraction), `300 + segment_count * 150` (speaker_attribution)
- Output tokens: `200 + segment_count * 30` (character_extraction), `100 + segment_count * 80` (speaker_attribution)
- TTS chars/sec: 5 chars/second for Chinese (rough average)

### API Endpoints
- `POST /api/cost/estimate` — Estimate cost for baking one chapter
- `GET /api/cost/estimate-book/{book_id}` — Estimate cost for an entire book

## Dependencies
- None (pure computation, no external dependencies)
