# Preflight Check — AI Agent Guide

## Purpose
Validate system readiness before generation: check tool availability (ffmpeg, ffprobe), LLM endpoint configuration, and TTS endpoint configuration. Returns a go/no-go decision with detailed check results.

## Key Concepts
- **Tool checks**: Verifies `ffmpeg` and `ffprobe` are in PATH
- **Endpoint checks**: Validates LLM and TTS endpoints are configured (non-empty)
- **Usage scenarios**: Supports "personal" usage scenario for future license policy checks

## Module: `vn_core/preflight/`

### `PreflightResult`
Dataclass: `can_proceed: bool`, `checks: list[dict]`, `warnings: list[str]`, `errors: list[str]`

### `PreflightCheck`

#### `check_tools() -> dict[str, bool]`
Returns `{"ffmpeg": bool, "ffprobe": bool}` using `shutil.which`.

#### `check_llm_endpoint(endpoint, api_key) -> dict`
Returns `{"available": bool, "endpoint": str}`.

#### `check_tts_endpoint(endpoint) -> dict`
Returns `{"available": bool, "endpoint": str}`.

#### `run_preflight(llm_endpoint, tts_endpoint, usage_scenario) -> PreflightResult`
1. Run tool checks (warnings for missing tools)
2. Check LLM endpoint (errors if not configured)
3. Check TTS endpoint (errors if not configured)
4. Set `can_proceed = len(errors) == 0`
5. Return aggregated result

## Usage
```python
preflight = PreflightCheck()
result = preflight.run_preflight(
    llm_endpoint="https://api.openai.com/v1",
    tts_endpoint="edge_tts",
)
if result.can_proceed:
    pipeline.cold_start(...)
```

## Dependencies
- `shutil` — stdlib, for tool discovery
