<script lang="ts">
  import type { TimingEntry } from "../types";

  interface Props {
    chapterId: string;
    htmlContent: string;
    timing: TimingEntry[];
    currentSegmentId: string;
    onSegmentClick: (segmentId: string, startMs: number) => void;
  }

  let {
    chapterId,
    htmlContent,
    timing,
    currentSegmentId,
    onSegmentClick,
  }: Props = $props();

  let containerRef: HTMLElement | undefined = $state();
  let timingMap: Map<string, TimingEntry> = $state(new Map());

  $effect(() => {
    const map = new Map<string, TimingEntry>();
    for (const t of timing) {
      map.set(t.segment_id, t);
    }
    timingMap = map;
  });

  function handleClick(e: MouseEvent) {
    const target = e.target as HTMLElement;
    const span = target.closest("[data-seg-id]");
    if (!span) return;
    const segId = span.getAttribute("data-seg-id");
    if (!segId) return;
    const entry = timingMap.get(segId);
    const startMs = entry?.start_ms ?? 0;
    onSegmentClick(segId, startMs);
  }

  function segmentClick(node: HTMLElement) {
    node.addEventListener("click", handleClick);
    return {
      destroy() {
        node.removeEventListener("click", handleClick);
      },
    };
  }

  $effect(() => {
    if (!containerRef || !currentSegmentId) return;
    const el = containerRef.querySelector(
      `[data-seg-id="${CSS.escape(currentSegmentId)}"]`
    );
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  });
</script>

<div class="chapter-reader" bind:this={containerRef}>
  {#if htmlContent}
    <div class="html-content" use:segmentClick>
      {@html htmlContent}
    </div>
  {:else}
    <p class="placeholder">Select a chapter to begin reading.</p>
  {/if}
</div>

<style>
  .chapter-reader {
    flex: 1;
    overflow-y: auto;
    padding: 1.5rem 2rem;
    max-width: 720px;
    margin: 0 auto;
    line-height: 1.8;
  }
  .html-content :global(.chapter) {
    font-size: 1.05rem;
  }
  .html-content :global(.chapter p) {
    margin: 0.8em 0;
    text-indent: 2em;
  }
  .html-content :global(.chapter span[data-seg-id]) {
    cursor: pointer;
    border-radius: 2px;
    transition: background-color 0.15s;
  }
  .html-content :global(.chapter span[data-seg-id]:hover) {
    background-color: rgba(170, 59, 255, 0.08);
  }
  .placeholder {
    color: var(--text);
    opacity: 0.6;
    text-align: center;
    margin-top: 3rem;
  }
</style>
