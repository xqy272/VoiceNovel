<script lang="ts">
  import type { BookInfo, TimingEntry } from "./types";
  import {
    bakeChapter,
    chapterAudioUrl,
    chapterHtmlUrl,
    createProject,
    getBuffer,
    getChapterContent,
    listProjects,
    prefetchChapter,
    resolveApiUrl,
  } from "./api";
  import AudioPlayer from "./lib/AudioPlayer.svelte";
  import ChapterList from "./lib/ChapterList.svelte";
  import ChapterReader from "./lib/ChapterReader.svelte";
  import StationPanel from "./lib/StationPanel.svelte";

  let books: BookInfo[] = $state([]);
  let selectedBookId = $state("");
  let selectedChapterId = $state("");
  let htmlContent = $state("");
  let timing: TimingEntry[] = $state([]);
  let audioUrl = $state("");
  let currentSegmentId = $state("");
  let currentTimeMs = $state(0);
  let isPlaying = $state(false);
  let seekMs = $state(-1);
  let error = $state("");
  let status = $state("");
  let loading = $state(false);
  let bookInput = $state("demo_mountain_inn");
  let sourceInput = $state("tests/golden_books/mountain_inn.txt");

  const selectedBook = $derived(
    books.find((book) => book.book_id === selectedBookId)
  );

  function savePosition() {
    if (!selectedBookId || !selectedChapterId) return;
    try {
      localStorage.setItem(
        "vn_position",
        JSON.stringify({
          bookId: selectedBookId,
          chapterId: selectedChapterId,
          segmentId: currentSegmentId,
          timeMs: currentTimeMs,
        })
      );
    } catch {}
  }

  function restorePosition(): {
    bookId: string;
    chapterId: string;
    segmentId: string;
    timeMs: number;
  } | null {
    try {
      const stored = localStorage.getItem("vn_position");
      if (stored) return JSON.parse(stored);
    } catch {}
    return null;
  }

  async function loadBooks() {
    loading = true;
    try {
      const result = await listProjects();
      books = Array.isArray(result) ? result : [result];
      error = "";
      if (!selectedBookId && books.length > 0) {
        selectedBookId = books[0].book_id;
        bookInput = books[0].book_id;
      }
    } catch (e: any) {
      error = `${
        e.message || "Failed to load projects"
      }. Confirm the API server is running on port 5000.`;
    } finally {
      loading = false;
    }
  }

  async function refreshProjects() {
    status = "Refreshing projects...";
    await loadBooks();
    if (!error) status = books.length ? "Projects loaded." : "No projects found.";
  }

  async function importSampleBook() {
    loading = true;
    error = "";
    status = "Importing sample book...";
    try {
      const bookId = bookInput.trim() || "demo_mountain_inn";
      await createProject(sourceInput.trim(), bookId);
      await loadBooks();
      selectedBookId = bookId;
      bookInput = bookId;
      selectedChapterId = "";
      htmlContent = "";
      timing = [];
      audioUrl = "";
      status = "Sample book imported. Select a chapter to bake and open.";
    } catch (e: any) {
      error = e.message || "Failed to import sample book";
      status = "";
    } finally {
      loading = false;
    }
  }

  async function selectBook(bookId: string) {
    const trimmed = bookId.trim();
    if (!trimmed) {
      error = "Enter a book ID or import the sample book first.";
      return;
    }

    const known = books.find((book) => book.book_id === trimmed);
    if (!known) {
      error = `Book "${trimmed}" is not imported yet. Import it first or choose an existing project.`;
      return;
    }

    selectedBookId = trimmed;
    bookInput = trimmed;
    selectedChapterId = "";
    htmlContent = "";
    timing = [];
    audioUrl = "";
    currentSegmentId = "";
    currentTimeMs = 0;
    status = "";
    error = "";
  }

  async function selectChapter(chapterId: string) {
    if (!selectedBookId) return;
    selectedChapterId = chapterId;
    htmlContent = "";
    timing = [];
    audioUrl = "";
    currentSegmentId = "";
    currentTimeMs = 0;
    error = "";
    loading = true;
    prefetchTriggered = new Set();

    try {
      // First, check if a buffer or full package already exists
      let contentUrl = "";
      let timingUrl = "";
      let audioBufUrl = "";
      try {
        const buf = await getBuffer(selectedBookId, chapterId);
        if (buf.content_url) {
          contentUrl = buf.content_url;
          timingUrl = buf.timing_url;
          audioBufUrl = buf.audio_url;
          status = `Loading ${chapterId} (${buf.status})...`;
        }
      } catch {
        // No buffer — need to bake
      }

      if (!contentUrl) {
        status = `Baking ${chapterId}...`;
        const bake = await bakeChapter(selectedBookId, chapterId);
        if (!bake.success) {
          throw new Error(bake.errors?.join("; ") || "Bake failed");
        }
        contentUrl = resolveApiUrl(
          chapterHtmlUrl(selectedBookId, chapterId),
        );
        timingUrl = resolveApiUrl(
          `/api/projects/${selectedBookId}/chapters/${chapterId}/timing`,
        );
        audioBufUrl = resolveApiUrl(
          chapterAudioUrl(selectedBookId, chapterId),
        );
      }

      status = `Loading ${chapterId}...`;

      // Load content from buffer or full URL
      htmlContent = await fetch(resolveApiUrl(contentUrl)).then((r) => {
        if (!r.ok) throw new Error(`Content not available: ${r.status}`);
        return r.text();
      });

      // Load timing from buffer or full URL
      timing = await fetch(resolveApiUrl(timingUrl)).then((r) => {
        if (!r.ok) throw new Error(`Timing not available: ${r.status}`);
        return r.json();
      });

      audioUrl = resolveApiUrl(audioBufUrl);
      status = `Ready: ${chapterId}`;
    } catch (e: any) {
      error = e.message || "Failed to load chapter";
      status = "";
    } finally {
      loading = false;
    }
  }

  function handleSegmentClick(segId: string, startMs: number) {
    currentSegmentId = segId;
    seekMs = startMs;
  }

  function handleSeeked() {
    seekMs = -1;
  }

  let prefetchTriggered: Set<string> = new Set();

  function handleTimeUpdate(ms: number) {
    currentTimeMs = ms;
    savePosition();

    // Trigger prefetch when playback > 60% through the chapter
    if (selectedBookId && selectedChapterId && timing.length > 0) {
      const lastEntry = timing[timing.length - 1];
      const totalMs = (lastEntry?.end_ms ?? 0) + (lastEntry?.gap_after_ms ?? 0);
      if (totalMs > 0 && ms > totalMs * 0.6) {
        const key = `${selectedBookId}:${selectedChapterId}`;
        if (!prefetchTriggered.has(key)) {
          prefetchTriggered.add(key);
          prefetchChapter(selectedBookId, selectedChapterId).catch(() => {});
        }
      }
    }
  }

  function handleSegmentChange(segId: string) {
    currentSegmentId = segId;
    highlightSegment(segId);
  }

  function highlightSegment(segId: string) {
    const container = document.querySelector(".html-content");
    if (!container) return;
    const prev = container.querySelector(".highlight");
    if (prev) prev.classList.remove("highlight");
    const el = container.querySelector(
      `[data-seg-id="${CSS.escape(segId)}"]`
    );
    if (el) el.classList.add("highlight");
  }

  function handlePlayPause() {
    isPlaying = !isPlaying;
  }

  $effect(() => {
    loadBooks();
    const pos = restorePosition();
    if (pos?.bookId) {
      selectedBookId = pos.bookId;
      bookInput = pos.bookId;
      if (pos.chapterId) selectChapter(pos.chapterId);
    }
  });
</script>

<div class="app-layout">
  <header class="app-header">
    <div class="brand">
      <h1 class="app-title">VoiceNovel Reader</h1>
      <span class="subtitle">MVP playback console</span>
    </div>
    <div class="top-actions">
      <button class="secondary" onclick={refreshProjects} disabled={loading}>
        Refresh
      </button>
      <button onclick={importSampleBook} disabled={loading}>
        Import Sample
      </button>
    </div>
  </header>

  <div class="app-body">
    <aside class="project-panel">
      <div class="panel-section">
        <label for="book-id">Book ID</label>
        <div class="row">
          <input
            id="book-id"
            type="text"
            placeholder="demo_mountain_inn"
            bind:value={bookInput}
          />
          <button class="secondary" onclick={() => selectBook(bookInput)} disabled={loading}>
            Load
          </button>
        </div>
      </div>

      <div class="panel-section">
        <label for="source-path">Source path</label>
        <input id="source-path" type="text" bind:value={sourceInput} />
      </div>

      {#if books.length > 0}
        <div class="panel-section">
          <label for="project-select">Projects</label>
          <select
            id="project-select"
            onchange={(e) => selectBook((e.target as HTMLSelectElement).value)}
          >
            {#each books as book}
              <option value={book.book_id} selected={book.book_id === selectedBookId}>
                {book.title || book.book_id}
              </option>
            {/each}
          </select>
        </div>
      {/if}

      <div class="panel-section status-block">
        {#if loading}
          <p class="status">Working...</p>
        {:else if status}
          <p class="status">{status}</p>
        {:else if selectedBook}
          <p class="status">{selectedBook.chapters.length} chapters available.</p>
        {:else}
          <p class="muted">Import the sample book or load an existing project.</p>
        {/if}
        {#if error}
          <p class="error">{error}</p>
        {/if}
      </div>
    </aside>

    {#if selectedBookId}
      <ChapterList
        bookId={selectedBookId}
        onSelect={selectChapter}
        selectedChapterId={selectedChapterId}
      />
      <StationPanel
        bookId={selectedBookId}
        selectedChapterId={selectedChapterId}
        onRefresh={() => selectChapter(selectedChapterId)}
      />
    {:else}
      <aside class="sidebar-placeholder">
        <p>No project selected.</p>
      </aside>
    {/if}

    <main class="content-area">
      <ChapterReader
        chapterId={selectedChapterId}
        {htmlContent}
        {timing}
        {currentSegmentId}
        onSegmentClick={handleSegmentClick}
      />
    </main>
  </div>

  {#if audioUrl && selectedChapterId}
    <AudioPlayer
      {audioUrl}
      {timing}
      {currentSegmentId}
      {currentTimeMs}
      {isPlaying}
      {seekMs}
      onTimeUpdate={handleTimeUpdate}
      onSegmentChange={handleSegmentChange}
      onPlayPause={handlePlayPause}
      onSeeked={handleSeeked}
    />
  {/if}
</div>

<style>
  :global(body) {
    margin: 0;
    font-family: system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
  }
  :global(.highlight) {
    background-color: #ffe082 !important;
    border-radius: 2px;
    transition: background-color 0.15s;
  }
  .app-layout {
    display: flex;
    flex-direction: column;
    height: 100vh;
  }
  .app-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 16px;
    border-bottom: 1px solid var(--border);
    background: var(--bg);
  }
  .brand {
    display: flex;
    align-items: baseline;
    gap: 12px;
    min-width: 0;
  }
  .app-title {
    font-size: 1.2rem;
    margin: 0;
    color: var(--text-h);
  }
  .subtitle {
    font-size: 0.8rem;
    color: var(--text);
  }
  .top-actions,
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .project-panel {
    width: 300px;
    border-right: 1px solid var(--border);
    padding: 1rem;
    overflow-y: auto;
  }
  .panel-section {
    margin-bottom: 14px;
  }
  label {
    display: block;
    margin-bottom: 5px;
    color: var(--text-h);
    font-size: 0.78rem;
    font-weight: 600;
  }
  input,
  select {
    width: 100%;
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 0.9rem;
    background: var(--bg);
    color: var(--text);
  }
  .row input {
    min-width: 0;
  }
  button {
    padding: 6px 14px;
    background: var(--accent);
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
    font-size: 0.85rem;
    white-space: nowrap;
  }
  button.secondary {
    background: var(--text-h);
  }
  button:hover {
    opacity: 0.9;
  }
  button:disabled {
    cursor: not-allowed;
    opacity: 0.55;
  }
  .app-body {
    display: flex;
    flex: 1;
    overflow: hidden;
  }
  .sidebar-placeholder {
    width: 220px;
    border-right: 1px solid var(--border);
    padding: 1rem;
    color: var(--text);
    opacity: 0.6;
  }
  .content-area {
    flex: 1;
    overflow-y: auto;
  }
  .status-block {
    border-top: 1px solid var(--border);
    padding-top: 12px;
  }
  .status,
  .muted {
    margin: 0;
    color: var(--text);
    font-size: 0.9rem;
  }
  .muted {
    opacity: 0.7;
  }
  .error {
    color: #e53e3e;
    margin: 8px 0 0;
    font-size: 0.85rem;
  }
</style>
