# LLM Gateway — AI Agent Guide

## Purpose
Unified interface for all LLM calls with caching, rate limiting, and automatic fallback. No service should call any LLM SDK directly — all calls go through this gateway.

## Key Concepts
- **Backend abstraction**: Mock (deterministic test), OpenAI (httpx-based), extensible via `register_backend`
- **Response caching**: SHA-256 cache key from task + model + messages + temperature; cached responses are returned instantly
- **Fallback chain**: openai → mock; if the primary backend fails, the next in chain is tried
- **Rate limiting**: Configurable minimum interval between calls per backend

## Module: `vn_core/llm_gateway/`

### Data Classes
- `LLMMessage(role, content)` — Single chat message
- `LLMRequest(task, messages, model, temperature, max_tokens, ...)` — Request with auto cache key
- `LLMResponse(task, content, model, usage, latency_ms, cached, error)` — Response with metadata

### `LLMGateway`

#### `register_backend(name, backend, set_default=False)`
Register a new LLM backend (must have `async generate(request) -> LLMResponse`).

#### `configure_openai(api_key, model, base_url)`
Quick-setup for OpenAI-compatible API. Sets as default if currently "mock".

#### `generate(request: LLMRequest) -> LLMResponse`
1. Compute cache key; return cached if hit
2. Call primary backend (request.model or default)
3. On error: try each fallback backend
4. Cache successful responses
5. Return response with cache/error status

### Backends

#### `MockLLMBackend`
Returns deterministic JSON for known tasks:
- `speaker_attribution` → narrator, confidence 0.5
- `reading_style` → neutral
- `text_adaptation` → empty operations
- `character_extraction` → empty characters
- `scene_summary` → generic summary
- Unknown tasks → `{"result": "mock response"}`

#### `OpenAILLMBackend(api_key, model, base_url)`
Calls OpenAI-compatible `/chat/completions` endpoint via httpx. Respects model, temperature, max_tokens from request.

## Dependencies
- `httpx` — optional, for OpenAI backend
- Standard library only for Mock backend
