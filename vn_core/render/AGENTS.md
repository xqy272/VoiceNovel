# Render (Speech Gateway) — AI Agent Guide

## Purpose
Speech Gateway routes TTS requests to adapters, handles fallback chains, and returns `TTSResult` with audio path and duration. The TTS Input Composer builds the final merged text + voice config for each segment.

## Key Concepts
- **Adapter pattern**: Each TTS engine is an adapter with `async synthesize(request) -> TTSResult`
- **Fallback chain**: cosyvoice → edge_tts → mock; if one fails, the next is tried with a modified request
- **Final merged text**: `BackendSpeechRequest.text` is the complete text to synthesize — adapters don't see source text
- **Concurrent synthesis**: The pipeline runs TTS with `asyncio.Semaphore` for parallelism control

## Module: `vn_core/render/`

### `TTSResult`
Dataclass: `request_id`, `segment_id`, `audio_path`, `duration_ms`, `engine`, `voice_id`, `status`, `error`

### `SpeechGateway(output_dir)`

#### `register_adapter(engine, adapter)`
Register a new TTS adapter by engine name.

#### `synthesize(request: BackendSpeechRequest) -> TTSResult`
1. Try the requested engine's adapter
2. On success: return result
3. On failure: iterate fallback_order, try each adapter with a modified request
4. If all fail: return error TTSResult

### `MockTTSAdapter(output_dir)`
- Generates silent WAV files (zero-byte PCM)
- Duration scales with text length: `max(500, len(text) * 100)` ms
- Sample rate: 24000 Hz, mono, 16-bit
- Engine name: `"mock"`

### `EdgeTTSAdapter(output_dir)`
- Uses `edge_tts` library for Microsoft Edge TTS
- Voice mapping: voice_id → Edge voice name (e.g., `edge_zh_narrator_001` → `zh-CN-XiaoxiaoNeural`)
- Outputs MP3 files
- Engine name: `"edge_tts"`

### `TTSInputComposer`
See `tts_input_composer.py` — builds `BackendSpeechRequest` from segment text, voice assignment, and reading style.

## Dependencies
- `vn_core.contracts.speech_request` — BackendSpeechRequest
- `edge_tts` — optional, for Edge TTS
- `wave` — stdlib, for mock WAV generation
