<script lang="ts">
  import type { ExceptionEntry } from "../types";
  import { listExceptions, resolveException } from "../api";

  let { bookId = "", chapterId = "", onChanged = () => {} } = $props();

  let items: ExceptionEntry[] = $state([]);
  let loading = $state(false);
  let error = $state("");
  let statusFilter = $state("open");

  async function load() {
    if (!bookId) return;
    loading = true;
    try {
      const st = statusFilter === "all" ? undefined : statusFilter;
      const resp = await listExceptions(bookId, st, chapterId || undefined);
      items = resp.exceptions;
      error = "";
    } catch (e: unknown) {
      error = (e as Error).message || "Failed";
    } finally {
      loading = false;
    }
  }

  async function handleResolve(excId: string) {
    try {
      await resolveException(excId);
      await load();
      onChanged();
    } catch (e: unknown) {
      error = (e as Error).message || "Resolve failed";
    }
  }

  $effect(() => { load(); });
</script>

<div class="tab-panel">
  <div class="tab-header">
    <strong>Exceptions</strong>
    <select bind:value={statusFilter} onchange={load} class="filt" aria-label="Filter by status">
      <option value="open">Open</option>
      <option value="user_resolved">Resolved</option>
      <option value="all">All</option>
    </select>
    <button class="btn-small" onclick={load} disabled={loading} aria-label="Refresh exceptions" title="Refresh">R</button>
  </div>
  {#if error}<p class="err">{error}</p>{/if}
  {#if loading}<p class="muted">loading...</p>{/if}
  {#each items as exc}
    <div class="exc-row">
      <span class="sev sev-{exc.severity}" title="{exc.severity}">{exc.severity[0]?.toUpperCase() || "?"}</span>
      <span class="type">{exc.exception_type}</span>
      <span class="unit">{exc.unit_id}</span>
      <span class="msg" title={exc.message}>{exc.message.slice(0, 40)}</span>
      {#if exc.status === "open"}
        <button class="btn-small" onclick={() => handleResolve(exc.exception_id)} aria-label="Resolve exception" title="Resolve">Ok</button>
      {/if}
    </div>
  {/each}
  {#if items.length === 0 && !loading}
    <p class="muted">No exceptions.</p>
  {/if}
</div>

<style>
  .tab-panel { font-size: 0.72rem; }
  .tab-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
  .filt { font-size: 0.65rem; padding: 1px 3px; border: 1px solid var(--border); border-radius: 2px; background: var(--bg); color: var(--text); }
  .err { color: #e53e3e; margin: 2px 0; }
  .muted { opacity: 0.6; margin: 2px 0; }
  .exc-row { display: flex; align-items: center; gap: 4px; padding: 2px 0; border-bottom: 1px solid var(--border); }
  .sev { font-weight: 700; padding: 0 3px; border-radius: 2px; font-size: 0.6rem; }
  .sev-high { background: #fed7d7; color: #9b2c2c; }
  .sev-medium { background: #fefcbf; color: #975a16; }
  .sev-low { background: #c6f6d5; color: #276749; }
  .type { font-family: monospace; font-size: 0.6rem; opacity: 0.8; }
  .unit { font-family: monospace; font-size: 0.6rem; }
  .msg { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.65rem; }
  .btn-small { font-size: 0.6rem; padding: 0 4px; border: 1px solid var(--border); border-radius: 2px; background: var(--bg); color: var(--text); cursor: pointer; }
  .btn-small:hover { opacity: 0.8; }
</style>
