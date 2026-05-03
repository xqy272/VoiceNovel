# Release Smoke Checklist

Manual verification steps for the MVP Candidate release.

Default: mock TTS (silent WAV) and mock LLM. No real API keys needed.

## Prerequisites

- Python 3.12 with `uv`
- Node.js with npm
- Ports 3000 and 5000 free
- PowerShell (recommended) or Command Prompt

## Quick Start

```powershell
./start.ps1
```

Wait for "Backend is ready" then open http://localhost:3000.

## Smoke Steps

### 1. Backend health

```powershell
curl http://localhost:5000/
# -> {"name":"VoiceNovel","version":"0.1.0","status":"ok"}

curl http://localhost:5000/health
# -> {"status":"ok",...}
```

- [ ] Root returns ok
- [ ] Health returns ok or degraded (ffmpeg warning acceptable)

### 2. Import sample book

In Web Reader or via curl:

```powershell
curl -X POST http://localhost:5000/api/projects -H "Content-Type: application/json" -d "{\"source_path\":\"tests/golden_books/mountain_inn.txt\",\"book_id\":\"demo\"}"
```

- [ ] Returns book_id "demo" with chapters
- [ ] GET /api/projects/demo returns book info

### 3. Cold start

```powershell
curl -X POST http://localhost:5000/api/projects/demo/chapters/ch001/cold-start
```

- [ ] Returns playable=true, segments_count > 0
- [ ] Buffer window package created
- [ ] Full bake job enqueued in background

### 4. Buffer assets (after cold start)

```powershell
curl http://localhost:5000/api/projects/demo/chapters/ch001/buffer
```

- [ ] GET buffer/content -> 200 HTML
- [ ] GET buffer/timing -> 200 JSON array
- [ ] GET buffer/manifest -> 200 JSON
- [ ] GET buffer/audio -> 200 WAV

### 5. Full bake

```powershell
curl -X POST http://localhost:5000/api/bake -H "Content-Type: application/json" -d "{\"book_id\":\"demo\",\"chapter_id\":\"ch001\"}"
```

- [ ] Returns success=true
- [ ] Station: full_package status = ready

### 6. Station

Open http://localhost:3000, expand Station panel (bottom bar).

- [ ] Chapters tab shows buffer=ready, full=ready
- [ ] Jobs tab/enumeration shows completed bake job
- [ ] Exceptions tab shows no open exceptions
- [ ] Voices tab lists characters
- [ ] Adaptation tab loads ops (may be empty for mock)

### 7. Preflight

```powershell
curl -X POST http://localhost:5000/api/projects/demo/chapters/ch001/preflight -H "Content-Type: application/json" -d "{\"operation\":\"export\",\"format\":\"daw\"}"
```

- [ ] ok=true
- [ ] checks include llm_gateway (pass), tts_engine (pass)
- [ ] estimated_cost present with all fields

### 8. Export DAW

In Station Xp tab or via curl:

```powershell
curl -X POST "http://localhost:5000/api/projects/demo/chapters/ch001/exports?format=daw"
```

- [ ] Returns 200 with artifact_version_id
- [ ] output_dir exists on disk

### 9. Download

```powershell
curl -o demo.zip "http://localhost:5000/api/projects/demo/exports/{artifact_version_id}/download"
```

- [ ] ZIP contains project.json, markers.json, regions.json, cue_sheet.txt
- [ ] All files non-empty

### 10. Web Reader playback

- [ ] Chapter list shown
- [ ] Click chapter -> content loads with text
- [ ] Audio plays (silent WAV with mock TTS -- progress bar moves)
- [ ] Sentence highlighting follows playback

## Automated Verification

```powershell
uv run --extra dev pytest tests/test_mvp_smoke.py -q
uv run --extra dev pytest tests -q
uv run --extra dev ruff check vn_core vn_server integrations tests
cd web_reader && npm run build
```

All three must pass with zero errors.

## Sign-off

- [ ] 10 manual smoke steps passed
- [ ] Automated test suite: all passed
- [ ] Lint: zero errors
- [ ] Frontend build: zero errors

Signed: ____________  Date: ____________
