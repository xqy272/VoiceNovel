<script lang="ts">
  import type { TimingEntry } from "../types";

  interface Props {
    audioUrl: string;
    timing: TimingEntry[];
    currentSegmentId: string;
    currentTimeMs: number;
    isPlaying: boolean;
    seekMs?: number;
    onTimeUpdate: (ms: number) => void;
    onSegmentChange: (segmentId: string) => void;
    onPlayPause: () => void;
    onSeeked?: () => void;
  }

  let {
    audioUrl,
    timing,
    currentSegmentId,
    currentTimeMs,
    isPlaying,
    seekMs = -1,
    onTimeUpdate,
    onSegmentChange,
    onPlayPause,
    onSeeked,
  }: Props = $props();

  let audioRef: HTMLAudioElement | undefined = $state();
  let durationMs = $state(0);
  let currentSegmentIdx = $state(-1);
  let prevIsPlaying = $state(false);
  let prevSeekMs = $state(-1);

  $effect(() => {
    if (!audioRef) return;
    audioRef.src = audioUrl;
    audioRef.load();
  });

  $effect(() => {
    if (!audioRef) return;
    if (isPlaying && !prevIsPlaying) {
      audioRef.play().catch(() => {});
    } else if (!isPlaying && prevIsPlaying) {
      audioRef.pause();
    }
    prevIsPlaying = isPlaying;
  });

  $effect(() => {
    if (!audioRef || seekMs < 0) return;
    if (seekMs !== prevSeekMs) {
      audioRef.currentTime = seekMs / 1000;
      prevSeekMs = seekMs;
      onSeeked?.();
    }
  });

  function handleTimeUpdate() {
    if (!audioRef) return;
    const ms = audioRef.currentTime * 1000;
    onTimeUpdate(ms);

    let idx = 0;
    for (let i = timing.length - 1; i >= 0; i--) {
      if (ms >= timing[i].start_ms) {
        idx = i;
        break;
      }
    }
    if (idx !== currentSegmentIdx) {
      currentSegmentIdx = idx;
      onSegmentChange(timing[idx]?.segment_id || "");
    }
  }

  function handleLoadedMetadata() {
    if (audioRef) {
      durationMs = audioRef.duration * 1000;
    }
  }

  function handleSeek(e: MouseEvent) {
    if (!audioRef) return;
    const bar = e.currentTarget as HTMLElement;
    const rect = bar.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    audioRef.currentTime = audioRef.duration * pct;
  }

  function formatTime(ms: number): string {
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, "0")}`;
  }

  const progressPct = $derived(
    durationMs > 0 ? (currentTimeMs / durationMs) * 100 : 0
  );
</script>

<div class="audio-player">
  <audio
    bind:this={audioRef}
    ontimeupdate={handleTimeUpdate}
    onloadedmetadata={handleLoadedMetadata}
  ></audio>

  <div class="controls">
    <button class="play-btn" onclick={onPlayPause}>
      {isPlaying ? "⏸" : "▶"}
    </button>

    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="progress-bar" role="slider" tabindex="0" aria-valuenow={Math.round(progressPct)} aria-valuemin={0} aria-valuemax={100} onclick={handleSeek} onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') handleSeek(e as unknown as MouseEvent); }}>
      <div class="progress-fill" style="width: {progressPct}%"></div>
    </div>

    <span class="time">
      {formatTime(currentTimeMs)} / {formatTime(durationMs)}
    </span>
  </div>

  {#if currentSegmentId}
    <div class="segment-info">
      <span class="seg-label">Segment:</span>
      <span class="seg-id">{currentSegmentId}</span>
    </div>
  {/if}
</div>

<style>
  .audio-player {
    border-top: 1px solid var(--border);
    padding: 12px 16px;
    background: var(--bg);
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .controls {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .play-btn {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 1px solid var(--border);
    background: var(--bg);
    cursor: pointer;
    font-size: 1rem;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.2s;
  }
  .play-btn:hover {
    background: var(--accent-bg);
    border-color: var(--accent-border);
  }
  .progress-bar {
    flex: 1;
    height: 6px;
    background: var(--border);
    border-radius: 3px;
    cursor: pointer;
    position: relative;
  }
  .progress-fill {
    height: 100%;
    background: var(--accent);
    border-radius: 3px;
    transition: width 0.1s linear;
  }
  .time {
    font-size: 0.8rem;
    color: var(--text);
    font-variant-numeric: tabular-nums;
    min-width: 80px;
    text-align: right;
  }
  .segment-info {
    font-size: 0.75rem;
    color: var(--text);
    opacity: 0.7;
  }
  .seg-label {
    font-weight: 600;
    margin-right: 4px;
  }
  .seg-id {
    font-family: var(--mono);
  }
</style>
