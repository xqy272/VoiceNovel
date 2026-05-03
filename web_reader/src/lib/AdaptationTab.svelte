<script lang="ts">
  import type { AdaptationDecisionRow, AdaptationOp } from "../types";
  import {
    listAdaptationOps, replayAdaptationOps, rollbackAdaptationOps,
    diffAdaptationText,
  } from "../api";

  let { bookId = "", chapterId = "", onChanged = () => {} } = $props();

  let rows: AdaptationDecisionRow[] = $state([]);
  let loading = $state(false);
  let error = $state("");
  let previewScope = $state("display_and_tts");
  let rollbackReason = $state("");
  let selectedIds: Set<string> = $state(new Set());
  let sourceText = $state("");
  let previewText = $state("");
  let replayWarnings: string[] = $state([]);
  let diffResult: { changes: { kind: string; before_span?: string; after_span?: string }[] } | null = $state(null);

  function getRawOp(row: AdaptationDecisionRow): AdaptationOp {
    return row.value || (row as unknown as AdaptationOp);
  }

  function getOpId(row: AdaptationDecisionRow): string {
    const raw = getRawOp(row);
    if (raw.op_id) return raw.op_id;
    return row.decision_type.replace("text_adaptation:", "");
  }

  async function load() {
    if (!bookId || !chapterId) return;
    loading = true;
    try {
      const resp = await listAdaptationOps(bookId, chapterId);
      rows = (resp.ops || []) as AdaptationDecisionRow[];
      error = "";
      selectedIds = new Set();
      previewText = "";
      replayWarnings = [];
      diffResult = null;
      rollbackReason = "";
      // Default sourceText to first raw op's original
      if (rows.length > 0) {
        sourceText = getRawOp(rows[0]).original || "";
      } else {
        sourceText = "";
      }
    } catch (e: unknown) {
      error = (e as Error).message || "Failed";
    } finally {
      loading = false;
    }
  }

  async function handleReplay() {
    if (!sourceText) return;
    try {
      const rawOps = rows.map(r => getRawOp(r)) as unknown as Record<string, unknown>[];
      const scopeVal = previewScope === "tts_only" ? "tts_only" : "display_and_tts";
      const resp = await replayAdaptationOps(bookId, chapterId, sourceText, rawOps, scopeVal);
      previewText = resp.text;
      replayWarnings = resp.warnings || [];
      diffResult = null;
    } catch (e: unknown) {
      error = (e as Error).message || "Replay failed";
    }
  }

  async function handleDiff() {
    if (!sourceText || !previewText) return;
    try {
      const resp = await diffAdaptationText(bookId, chapterId, sourceText, previewText);
      diffResult = resp as { changes: { kind: string; before_span?: string; after_span?: string }[] };
    } catch (e: unknown) {
      error = (e as Error).message || "Diff failed";
    }
  }

  function toggleSelect(opId: string) {
    const next = new Set(selectedIds);
    if (next.has(opId)) next.delete(opId);
    else next.add(opId);
    selectedIds = next;
  }

  async function handleRollback() {
    if (selectedIds.size === 0 || !rollbackReason) return;
    try {
      await rollbackAdaptationOps(bookId, chapterId, [...selectedIds], rollbackReason);
      selectedIds = new Set();
      rollbackReason = "";
      previewText = "";
      replayWarnings = [];
      diffResult = null;
      onChanged();
      await load();
    } catch (e: unknown) {
      error = (e as Error).message || "Rollback failed";
    }
  }

  $effect(() => { if (bookId && chapterId) load(); });
</script>

<div class="tab-panel">
  <div class="tab-header">
    <strong>Adaptation</strong>
    <button class="btn-small" onclick={load} disabled={loading} aria-label="Refresh ops" title="Refresh">R</button>
  </div>
  {#if error}<p class="err">{error}</p>{/if}
  {#if loading}<p class="muted">loading...</p>{/if}

  <div class="src-row">
    <input type="text" bind:value={sourceText} placeholder="Source text for replay"
           class="src-input" aria-label="Source text for replay" />
    <select bind:value={previewScope} class="filt" aria-label="Replay scope">
      <option value="display_and_tts">Display</option>
      <option value="tts_only">TTS</option>
    </select>
    <button class="btn-small" onclick={handleReplay} disabled={!sourceText || loading} aria-label="Replay preview" title="Replay">Play</button>
    {#if previewText}
      <button class="btn-small" onclick={handleDiff} aria-label="Diff source vs replay" title="Diff">Diff</button>
    {/if}
  </div>

  {#each rows as row}
    {@const raw = getRawOp(row)}
    {@const oid = getOpId(row)}
    <div class="op-row">
      <input type="checkbox" checked={selectedIds.has(oid)} onchange={() => toggleSelect(oid)} aria-label="Select op {oid}" />
      <span class="seg" title={raw.segment_id}>{(raw.segment_id || "?").slice(-14)}</span>
      <span class="scope">{raw.scope || "?"}</span>
      <span class="orig" title={raw.original}>{raw.original?.slice(0, 30) || "?"}</span>
      <span class="arrow">&#8594;</span>
      <span class="norm" title={raw.normalized}>{raw.normalized?.slice(0, 30) || "?"}</span>
    </div>
  {/each}

  {#if previewText}
    <div class="preview-box"><pre>{previewText}</pre></div>
  {/if}
  {#if replayWarnings.length > 0}
    <div class="warn-box">Warnings: {replayWarnings.join("; ")}</div>
  {/if}

  {#if diffResult}
    <div class="diff-box">
      <strong>Diff</strong> ({diffResult.changes.length} changes):
      {#each diffResult.changes as ch}
        <div class="diff-line">
          <span class="diff-kind">{ch.kind}</span>
          {#if ch.before_span}<span class="diff-before">{ch.before_span}</span>{/if}
          {#if ch.after_span}<span class="diff-after">{ch.after_span}</span>{/if}
        </div>
      {/each}
    </div>
  {/if}

  {#if selectedIds.size > 0}
    <div class="rollback-bar">
      <input type="text" bind:value={rollbackReason} placeholder="rollback reason" class="rb-input" aria-label="Rollback reason" />
      <button class="btn-small" onclick={handleRollback} disabled={!rollbackReason} aria-label="Rollback selected" title="Rollback selected ops">Rollback ({selectedIds.size})</button>
    </div>
  {/if}
  {#if rows.length === 0 && !loading}
    <p class="muted">No ops.</p>
  {/if}
</div>

<style>
  .tab-panel { font-size: 0.72rem; }
  .tab-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
  .filt { font-size: 0.65rem; padding: 1px 3px; border: 1px solid var(--border); border-radius: 2px; background: var(--bg); color: var(--text); }
  .err { color: #e53e3e; margin: 2px 0; }
  .muted { opacity: 0.6; margin: 2px 0; }
  .src-row { display: flex; gap: 4px; margin-bottom: 6px; }
  .src-input { flex: 1; font-size: 0.65rem; padding: 2px 4px; border: 1px solid var(--border); border-radius: 2px; background: var(--bg); color: var(--text); }
  .op-row { display: flex; align-items: center; gap: 3px; padding: 2px 0; border-bottom: 1px solid var(--border); font-size: 0.62rem; }
  .seg { font-family: monospace; opacity: 0.6; }
  .scope { font-size: 0.55rem; padding: 0 2px; border-radius: 2px; background: #bee3f8; }
  .orig { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 80px; }
  .arrow { opacity: 0.5; }
  .norm { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 80px; color: #2b6cb0; }
  .preview-box { margin-top: 6px; padding: 4px; background: #f7fafc; border: 1px solid var(--border); border-radius: 2px; font-family: monospace; font-size: 0.65rem; max-height: 100px; overflow-y: auto; }
  .preview-box pre { margin: 0; white-space: pre-wrap; }
  .warn-box { margin-top: 4px; padding: 3px; background: #fffbeb; border: 1px solid #ecc94b; border-radius: 2px; font-size: 0.6rem; color: #975a16; }
  .diff-box { margin-top: 6px; padding: 4px; background: #fffbeb; border: 1px solid var(--border); border-radius: 2px; font-size: 0.65rem; }
  .diff-line { font-family: monospace; font-size: 0.6rem; padding: 1px 0; }
  .diff-kind { font-weight: 700; margin-right: 6px; }
  .diff-before { color: #e53e3e; text-decoration: line-through; margin-right: 4px; }
  .diff-after { color: #38a169; }
  .rollback-bar { display: flex; gap: 4px; margin-top: 6px; }
  .rb-input { flex: 1; font-size: 0.65rem; padding: 2px 4px; border: 1px solid var(--border); border-radius: 2px; background: var(--bg); color: var(--text); }
  .btn-small { font-size: 0.6rem; padding: 0 4px; border: 1px solid var(--border); border-radius: 2px; background: var(--bg); color: var(--text); cursor: pointer; }
  .btn-small:hover { opacity: 0.8; }
</style>
