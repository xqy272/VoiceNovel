# Web Reader — AI Agent Guide

## Purpose
Svelte 5 reference reader client for VoiceNovel. Displays chapter text with
segment-level highlighting synchronized to audio playback.

## Architecture
```
web_reader/
├── src/
│   ├── App.svelte            — Main app layout (header + sidebar + reader + player)
│   ├── api.ts                — API client for vn_server REST endpoints
│   ├── types.ts              — TypeScript interfaces matching Contracts
│   ├── main.ts               — App entry point
│   ├── app.css               — Global CSS variables and dark mode
│   └── lib/
│       ├── ChapterList.svelte — Sidebar chapter picker
│       ├── ChapterReader.svelte — Segmented text with click-to-seek + highlight
│       └── AudioPlayer.svelte — Audio transport with segment tracking
├── vite.config.ts            — Dev proxy to localhost:5000
└── package.json
```

## Key Concepts
- **Segment ID highlighting**: `data-seg-id` spans in XHTML match timing entries
- **Click-to-seek**: Clicking a segment seeks audio to that segment's `start_ms`
- **Audio-time sync**: AudioPlayer resolves current segment from `currentTime`
- **Reader Adapter Protocol**: Uses `/api/reader-adapter` to discover chapter URLs

## API Endpoints Used
- `GET /api/projects` — List projects
- `GET /api/projects/{book_id}/chapters` — List chapters
- `POST /api/reader-adapter` — Get chapter URLs (content, audio, timing)
- `GET /api/projects/{book_id}/chapters/{chapter_id}/content` — XHTML content
- `GET /api/projects/{book_id}/chapters/{chapter_id}/timing` — Timing JSON
- `GET /api/projects/{book_id}/chapters/{chapter_id}/audio` — Audio file

## Running
```bash
cd web_reader
npm install
npm run dev    # Dev server on :3000 with proxy to :5000
npm run build  # Production build to dist/
```

## Data Flow
1. User enters/selects Book ID → loads chapter list
2. User selects chapter → API fetches content + timing + audio URL
3. ChapterReader renders XHTML with `data-seg-id` spans
4. AudioPlayer tracks `timeupdate` → resolves current segment
5. Current segment gets `.highlight` class + auto-scroll
6. Click on segment → seeks audio to `start_ms`