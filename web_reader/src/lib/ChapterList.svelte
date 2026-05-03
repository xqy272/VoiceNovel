<script lang="ts">
  import type { ChapterInfo } from "../types";
  import { listChapters } from "../api";

  interface Props {
    bookId: string;
    onSelect: (chapterId: string) => void;
    selectedChapterId?: string;
  }

  let { bookId, onSelect, selectedChapterId = "" }: Props = $props();

  let chapters: ChapterInfo[] = $state([]);
  let loading = $state(false);
  let error = $state("");

  async function load() {
    loading = true;
    error = "";
    try {
      const result = await listChapters(bookId);
      chapters = result as ChapterInfo[];
    } catch (e: any) {
      error = e.message || "Failed to load chapters";
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (bookId) load();
  });
</script>

<div class="chapter-list">
  <h3>Chapters</h3>
  {#if loading}
    <p class="loading">Loading...</p>
  {:else if error}
    <p class="error">{error}</p>
  {:else if chapters.length === 0}
    <p class="empty">No chapters found.</p>
  {:else}
    <ul>
      {#each chapters as ch}
        <li>
          <button
            class="chapter-btn"
            class:active={ch.chapter_id === selectedChapterId}
            onclick={() => onSelect(ch.chapter_id)}
          >
            {ch.title || ch.chapter_id}
            <span class="count">{ch.paragraph_count} paragraphs</span>
          </button>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .chapter-list {
    border-right: 1px solid var(--border);
    padding: 1rem;
    min-width: 220px;
    overflow-y: auto;
    height: 100%;
  }
  h3 {
    margin: 0 0 0.75rem 0;
    font-size: 1.1rem;
    color: var(--text-h);
  }
  ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  li {
    margin-bottom: 4px;
  }
  .chapter-btn {
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
    padding: 8px 12px;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.9rem;
    color: var(--text);
    text-align: left;
    transition: background 0.2s, border-color 0.2s;
  }
  .chapter-btn:hover {
    background: var(--accent-bg);
    border-color: var(--accent-border);
  }
  .chapter-btn.active {
    background: var(--accent-bg);
    border-color: var(--accent);
    color: var(--text-h);
    font-weight: 600;
  }
  .count {
    font-size: 0.75rem;
    color: var(--text);
    opacity: 0.7;
  }
  .loading, .empty, .error {
    color: var(--text);
    font-style: italic;
  }
  .error {
    color: #e53e3e;
  }
</style>