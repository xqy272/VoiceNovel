<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import type { JobRow, StationData } from "../types";
  import {
    getStation,
    retryJob,
    cancelJob,
    coldStartChapter,
    rebuildChapter,
    exportChapter,
    listExports,
    exportDownloadUrl,
    preflightChapter,
    type PreflightResult,
  } from "../api";
  import type { ArtifactSummary } from "../types";
  import ExceptionsTab from "./ExceptionsTab.svelte";
  import VoicesTab from "./VoicesTab.svelte";
  import AdaptationTab from "./AdaptationTab.svelte";

  let { bookId = "", selectedChapterId = "", onRefresh = () => {} } = $props();

  let data: StationData | null = $state(null);
  let previousReady: Record<string, boolean> = {};
  let loading = $state(false);
  let error = $state("");
  let tab = $state("chapters");
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let exports: ArtifactSummary[] = $state([]);
  let preflight: PreflightResult | null = $state(null);
  let pfLoading = $state(false);
  let pfOperation = $state("bake");

  async function loadPreflight(operation: string = "bake") {
    if (!bookId || !selectedChapterId) return;
    pfLoading = true;
    pfOperation = operation;
    try {
      preflight = await preflightChapter(bookId, selectedChapterId, operation);
    } catch (e: unknown) {
      preflight = null;
      error = (e as Error).message || "Preflight failed";
    } finally {
      pfLoading = false;
    }
  }

  async function loadExports() {
    if (!bookId) return;
    try {
      const chId = selectedChapterId || "";
      const res = await listExports(bookId, chId || undefined);
      exports = (res.exports || []) as ArtifactSummary[];
    } catch {
      exports = [];
    }
  }

  function jobKind(job: JobRow): "rebuild" | "prefetch" | "bake" {
    const cacheBuster = String(job.cache_buster || "");
    const jobId = String(job.job_id || "");
    if (job.job_kind) return job.job_kind;
    if (cacheBuster.startsWith("rebuild:") || jobId.startsWith("job_rebuild_")) {
      return "rebuild";
    }
    if (cacheBuster.startsWith("prefetch:") || jobId.startsWith("job_prefetch_")) {
      return "prefetch";
    }
    return "bake";
  }

  function isActiveJob(job: JobRow) {
    return job.status === "pending" || job.status === "running";
  }

  function activeJob(ch: StationData["chapters"][number], kind: "rebuild" | "prefetch") {
    return ch.jobs.find((job) => jobKind(job) === kind && isActiveJob(job));
  }

  async function load() {
    if (!bookId) return;
    loading = true;
    try {
      const newData = await getStation(bookId);
      error = "";
      // Auto-refresh reader when a chapter transitions to ready
      if (data) {
        for (const ch of newData.chapters) {
          const prevReady = previousReady[ch.chapter_id] || false;
          const nowReady = ch.progress.full_ready;
          if (!prevReady && nowReady && ch.chapter_id === selectedChapterId) {
            onRefresh();
          }
          previousReady[ch.chapter_id] = nowReady;
        }
      } else {
        for (const ch of newData.chapters) {
          previousReady[ch.chapter_id] = ch.progress.full_ready;
        }
      }
      data = newData;
    } catch (e: unknown) {
      error = (e as Error).message || "Failed to load station";
    } finally {
      loading = false;
    }
  }

  async function handleColdStart(chapterId: string) {
    try {
      await coldStartChapter(bookId, chapterId);
      await load();
      onRefresh();
    } catch (e: unknown) {
      error = (e as Error).message || "Cold start failed";
    }
  }

  async function handleRebuild(chapterId: string) {
    try {
      await rebuildChapter(bookId, chapterId);
      await load();
    } catch (e: unknown) {
      error = (e as Error).message || "Rebuild failed";
    }
  }

  async function handleRetry(jobId: string) {
    try {
      await retryJob(jobId);
      await load();
    } catch (e: unknown) {
      error = (e as Error).message || "Retry failed";
    }
  }

  async function handleCancel(jobId: string) {
    try {
      await cancelJob(jobId);
      await load();
    } catch (e: unknown) {
      error = (e as Error).message || "Cancel failed";
    }
  }

  onMount(() => {
    load();
    pollTimer = setInterval(load, 5000);
  });

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
  });
</script>

<div class="station-panel">
  <div class="station-header">
    <strong>Station</strong>
    {#if loading}
      <span class="muted">updating...</span>
    {/if}
    <button class="btn-small" onclick={load} disabled={loading}
            aria-label="Refresh station" title="Refresh">R</button>
  </div>

  {#if error}
    <p class="station-error">{error}</p>
  {/if}

  <!-- Tabs -->
  <div class="tab-bar">
    <button class="tab-btn" class:active={tab === "chapters"} onclick={() => tab = "chapters"}
            aria-label="Chapters tab" title="Chapters">Ch</button>
    <button class="tab-btn" class:active={tab === "exceptions"} onclick={() => tab = "exceptions"}
            aria-label="Exceptions tab" title="Exceptions">Ex</button>
    <button class="tab-btn" class:active={tab === "voices"} onclick={() => tab = "voices"}
            aria-label="Voices tab" title="Voices">Vo</button>
    <button class="tab-btn" class:active={tab === "adaptation"} onclick={() => tab = "adaptation"}
            aria-label="Adaptation tab" title="Adaptation">Ad</button>
    <button class="tab-btn" class:active={tab === "export"} onclick={() => { tab = "export"; loadExports(); }}
            aria-label="Export tab" title="Export">Xp</button>
    <button class="tab-btn" class:active={tab === "preflight"} onclick={() => { tab = "preflight"; loadPreflight(); }}
            aria-label="Preflight tab" title="Preflight">Pf</button>
  </div>

  {#if data}
    <!-- Chapters tab -->
    {#if tab === "chapters"}
      <div class="queue-bar">
        Q: {data.queue.pending}p {data.queue.running}r {data.queue.done}d {data.queue.failed}f
      </div>

      {#each data.chapters as ch}
        {@const rebuildJob = activeJob(ch, "rebuild")}
        {@const prefetchJob = activeJob(ch, "prefetch")}
        <div class="chapter-card">
          <div class="ch-title">{ch.chapter_id}</div>
          <div class="ch-status">
            <span class:ok={ch.buffer.status === "ready"}
                  class:stale={ch.buffer.status === "stale"}
                  class:bad={ch.buffer.status !== "ready" && ch.buffer.status !== "stale"}
                  title="Buffer: {ch.buffer.status}">
              B:{ch.buffer.status[0]}
            </span>
            <span class:ok={ch.full_package.status === "ready"}
                  class:stale={ch.full_package.status === "stale"}
                  class:bad={ch.full_package.status !== "ready" && ch.full_package.status !== "stale"}
                  title="Full: {ch.full_package.status}">
              F:{ch.full_package.status[0]}
            </span>
            {#if ch.exceptions.length > 0}
              <span class="warn" title="{ch.exceptions.length} open exception(s)">!{ch.exceptions.length}</span>
            {/if}
          </div>

          {#if ch.progress.needs_rebuild || rebuildJob || prefetchJob}
            {#if rebuildJob}
              <span class="rebuild-status" title={"Rebuild: " + rebuildJob.status}>
                Rebuild {rebuildJob.status}
              </span>
            {:else if prefetchJob}
              <span class="prefetch-status" title={"Prefetch: " + prefetchJob.status}>
                Prefetch {prefetchJob.status}
              </span>
            {:else}
              <button class="btn-small" onclick={() => handleRebuild(ch.chapter_id)}
                      aria-label="Rebuild chapter" title="Rebuild">Rebuild</button>
            {/if}
          {/if}

          {#each ch.jobs as job}
            <div class="job-row">
              <span class="job-id">{String(job.job_id).slice(0, 16)}</span>
              <span class="job-type" title={jobKind(job)}>
                {jobKind(job) === "rebuild" ? "R" : jobKind(job) === "prefetch" ? "P" : "B"}</span>
              <span class="job-status">{job.status}</span>
              {#if job.status === "failed"}
                <button class="btn-small" onclick={() => handleRetry(String(job.job_id))}
                        aria-label="Retry job" title="Retry">Retry</button>
              {/if}
              {#if job.status === "pending" || job.status === "running"}
                <button class="btn-small" onclick={() => handleCancel(String(job.job_id))}
                        aria-label="Cancel job" title="Cancel">X</button>
              {/if}
            </div>
          {/each}

          <button class="btn-small" onclick={() => handleColdStart(ch.chapter_id)}
                  aria-label="Cold start chapter" title="Cold Start">Cold Start</button>
        </div>
      {/each}
    {/if}

    <!-- Exceptions tab -->
    {#if tab === "exceptions"}
      <ExceptionsTab {bookId} chapterId={selectedChapterId} onChanged={load} />
    {/if}

    <!-- Voices tab -->
    {#if tab === "voices"}
      <VoicesTab {bookId} onChanged={load} />
    {/if}

    <!-- Adaptation tab -->
    {#if tab === "adaptation"}
      <AdaptationTab {bookId} chapterId={selectedChapterId} onChanged={load} />
    {/if}

    <!-- Export tab -->
    {#if tab === "export"}
      {@const ch = data.chapters.find(c => c.chapter_id === selectedChapterId) || data.chapters[0]}
      <div class="tab-panel">
        <div class="tab-header"><strong>Export</strong></div>
        {#if ch}
          <div class="export-row">
            <span>Chapter: {ch.chapter_id}</span>
            <span class="export-status" class:ok={ch.full_package.status === "ready"}>
              {ch.full_package.status}
            </span>
          </div>
          {#each ["daw", "audiobookshelf", "m4b"] as fmt}
            <div class="export-row">
              <span>{fmt}</span>
              <button class="btn-small"
                      disabled={ch.full_package.status !== "ready"}
                      onclick={async () => {
                        try {
                          await exportChapter(bookId, ch.chapter_id, fmt);
                          await load();
                          await loadExports();
                        } catch (e: unknown) { error = (e as Error).message; }
                      }}
                      aria-label={`Export ${fmt}`} title={`Export ${fmt}`}>Export</button>
            </div>
          {/each}

          {#if exports.length > 0}
            <div class="export-list-header">Exported artifacts</div>
            {#each exports as exp}
              {@const invReason = String(exp.invalidated_reason || "")}
              {@const isActive = exp.status === "active"}
              <div class="export-artifact-row">
                <span class="export-fmt">{String(exp.artifact_type).replace("export_", "")}</span>
                <span class="export-vid" title={String(exp.artifact_version_id)}>
                  {String(exp.artifact_version_id).slice(-20)}
                </span>
                <span class="export-st" class:active={isActive}
                      class:stale={exp.status === "invalidated"}
                      class:inactive={!isActive && exp.status !== "invalidated"}>
                  {exp.status}
                </span>
                {#if invReason}
                  <span class="export-reason" title={invReason}>{invReason.slice(0, 24)}</span>
                {/if}
                {#if isActive}
                  <a class="btn-small export-dl-btn"
                     href={exportDownloadUrl(bookId, String(exp.artifact_version_id))}
                     download
                     aria-label="Download {String(exp.artifact_type)}"
                     title="Download">DL</a>
                {/if}
              </div>
            {/each}
          {:else}
            <p class="muted">No exports yet.</p>
          {/if}
        {:else}
          <p class="muted">No chapter selected.</p>
        {/if}
      </div>
    {/if}

    <!-- Preflight tab -->
    {#if tab === "preflight"}
      <div class="tab-panel">
        <div class="tab-header"><strong>Preflight</strong></div>
        {#if selectedChapterId}
          <div class="pf-ops">
            {#each ["bake", "cold_start", "rebuild", "export"] as op}
              <button class="btn-small" class:active-op={pfOperation === op}
                      disabled={pfLoading}
                      onclick={() => loadPreflight(op)}
                      aria-label={`Preflight ${op}`}>{op.replace("_", " ")}</button>
            {/each}
          </div>
        {/if}

        {#if pfLoading}
          <p class="muted">Checking...</p>
        {:else if preflight}
          <div class="pf-summary" class:pf-ok={preflight.ok} class:pf-fail={!preflight.ok}>
            <span class="pf-ok-text">{preflight.ok ? "Ready" : "Blocked"}</span>
          </div>

          {#if preflight.blocking_errors.length > 0}
            <div class="pf-section">
              <div class="pf-section-title">Blocking</div>
              {#each preflight.blocking_errors as be}
                <div class="pf-err">{be}</div>
              {/each}
            </div>
          {/if}

          {#if preflight.warnings.length > 0}
            <div class="pf-section">
              <div class="pf-section-title">Warnings</div>
              {#each preflight.warnings as w}
                <div class="pf-warn">{w}</div>
              {/each}
            </div>
          {/if}

          <div class="pf-section">
            <div class="pf-section-title">Checks</div>
            {#each preflight.checks as c}
              <div class="pf-check">
                <span class="pf-check-dot" class:pass={c.status === "pass"}
                      class:warn={c.status === "warn"}
                      class:fail={c.status === "fail"}></span>
                <span class="pf-check-name">{c.name}</span>
                <span class="pf-check-msg">{c.message}</span>
              </div>
            {/each}
          </div>

          {#if preflight.estimated_cost}
            <div class="pf-section">
              <div class="pf-section-title">Cost estimate</div>
              <div class="pf-cost-grid">
                <span>Segments</span><span>{preflight.estimated_cost.segment_count_est}</span>
                <span>TTS chars</span><span>{preflight.estimated_cost.tts_total_chars}</span>
                <span>Duration</span><span>{preflight.estimated_cost.total_duration_minutes} min</span>
                <span>LLM cost</span><span>${preflight.estimated_cost.llm_cost_usd.toFixed(4)}</span>
                <span>TTS cost</span><span>${preflight.estimated_cost.tts_cost_usd.toFixed(4)}</span>
                <span><strong>Total</strong></span><span><strong>${preflight.estimated_cost.total_cost_usd.toFixed(4)}</strong></span>
              </div>
            </div>
          {/if}
        {:else}
          <p class="muted">Select an operation to run preflight.</p>
        {/if}
      </div>
    {/if}
  {/if}
</div>

<style>
  .station-panel {
    font-size: 0.75rem;
    padding: 8px;
    border-top: 1px solid var(--border);
  }
  .station-header {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 6px;
  }
  .muted { opacity: 0.6; font-size: 0.7rem; }
  .station-error { color: #e53e3e; margin: 4px 0; }
  .queue-bar { margin-bottom: 6px; font-family: monospace; font-size: 0.7rem; }
  .tab-bar { display: flex; gap: 2px; margin-bottom: 8px; }
  .tab-btn {
    font-size: 0.65rem;
    padding: 2px 8px;
    border: 1px solid var(--border);
    border-radius: 2px;
    background: var(--bg);
    color: var(--text);
    cursor: pointer;
  }
  .tab-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }
  .chapter-card {
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: 6px;
    margin-bottom: 6px;
  }
  .ch-title { font-weight: 600; margin-bottom: 4px; }
  .ch-status { display: flex; gap: 8px; margin-bottom: 4px; }
  .ok { color: #38a169; }
  .stale { color: #dd6b20; }
  .bad { color: #a0aec0; }
  .rebuild-status { font-size: 0.65rem; padding: 1px 4px; border-radius: 2px; background: #bee3f8; }
  .prefetch-status { font-size: 0.65rem; padding: 1px 4px; border-radius: 2px; background: #c6f6d5; }
  .warn { color: #ecc94b; }
  .job-row {
    display: flex;
    align-items: center;
    gap: 6px;
    font-family: monospace;
    font-size: 0.7rem;
    padding: 2px 0;
  }
  .job-id { opacity: 0.7; }
  .job-type { font-size: 0.55rem; padding: 0 2px; border-radius: 2px; background: #e2e8f0; }
  .job-status {
    padding: 0 4px;
    border-radius: 2px;
    background: var(--border);
  }
  .btn-small {
    font-size: 0.65rem;
    padding: 1px 5px;
    border: 1px solid var(--border);
    border-radius: 2px;
    background: var(--bg);
    color: var(--text);
    cursor: pointer;
  }
  .btn-small:hover { opacity: 0.8; }
  .export-row { display: flex; align-items: center; gap: 8px; padding: 3px 0; font-size: 0.72rem; }
  .export-status.ok { color: #38a169; }
  .export-status { color: #a0aec0; }
  .export-list-header { font-size: 0.7rem; font-weight: 600; margin-top: 10px; margin-bottom: 4px; border-top: 1px solid var(--border); padding-top: 6px; }
  .export-artifact-row {
    display: flex;
    align-items: center;
    gap: 6px;
    font-family: monospace;
    font-size: 0.65rem;
    padding: 2px 0;
  }
  .export-fmt { font-weight: 600; min-width: 48px; }
  .export-vid { opacity: 0.7; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 140px; }
  .export-st { padding: 0 3px; border-radius: 2px; font-size: 0.6rem; }
  .export-st.active { background: #c6f6d5; color: #22543d; }
  .export-st.stale { background: #fed7aa; color: #9c4221; }
  .export-st.inactive { background: #e2e8f0; color: #4a5568; }
  .export-reason { font-size: 0.55rem; opacity: 0.6; max-width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .export-dl-btn { text-decoration: none; margin-left: auto; }
  /* Preflight tab */
  .pf-ops { display: flex; gap: 2px; margin-bottom: 8px; }
  .btn-small.active-op { background: var(--accent); color: #fff; border-color: var(--accent); }
  .pf-summary { padding: 6px 8px; border-radius: 4px; margin-bottom: 8px; font-weight: 600; }
  .pf-ok { background: #c6f6d5; color: #22543d; }
  .pf-fail { background: #fed7d7; color: #9b2c2c; }
  .pf-section { margin-bottom: 8px; }
  .pf-section-title { font-size: 0.65rem; font-weight: 600; text-transform: uppercase; margin-bottom: 3px; opacity: 0.7; }
  .pf-err { font-size: 0.65rem; color: #e53e3e; padding: 2px 0; }
  .pf-warn { font-size: 0.65rem; color: #dd6b20; padding: 2px 0; }
  .pf-check { display: flex; align-items: center; gap: 5px; font-size: 0.65rem; padding: 2px 0; }
  .pf-check-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
  .pf-check-dot.pass { background: #38a169; }
  .pf-check-dot.warn { background: #dd6b20; }
  .pf-check-dot.fail { background: #e53e3e; }
  .pf-check-name { min-width: 90px; font-weight: 500; }
  .pf-check-msg { opacity: 0.7; }
  .pf-cost-grid { display: grid; grid-template-columns: auto auto; gap: 2px 12px; font-size: 0.65rem; font-family: monospace; }
</style>
