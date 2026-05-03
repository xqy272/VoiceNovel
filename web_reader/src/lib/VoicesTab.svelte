<script lang="ts">
  import type { VoiceAssignment } from "../types";
  import { listVoiceAssignments, lockVoiceAssignment, unlockVoiceAssignment, recastUnlockedVoiceAssignments } from "../api";

  let { bookId = "", onChanged = () => {} } = $props();

  let items: VoiceAssignment[] = $state([]);
  let loading = $state(false);
  let error = $state("");

  async function load() {
    if (!bookId) return;
    loading = true;
    try {
      const resp = await listVoiceAssignments(bookId);
      items = resp.assignments;
      error = "";
    } catch (e: unknown) {
      error = (e as Error).message || "Failed";
    } finally {
      loading = false;
    }
  }

  async function handleLock(va: VoiceAssignment) {
    try {
      await lockVoiceAssignment(bookId, va.character_id, va.voice_id);
      await load();
      onChanged();
    } catch (e: unknown) {
      error = (e as Error).message || "Lock failed";
    }
  }

  async function handleUnlock(va: VoiceAssignment) {
    try {
      await unlockVoiceAssignment(bookId, va.character_id);
      await load();
      onChanged();
    } catch (e: unknown) {
      error = (e as Error).message || "Unlock failed";
    }
  }

  async function handleRecast() {
    try {
      await recastUnlockedVoiceAssignments(bookId);
      await load();
      onChanged();
    } catch (e: unknown) {
      error = (e as Error).message || "Recast failed";
    }
  }

  function statusClass(s: string): string {
    if (s === "user_locked") return "st-locked";
    if (s === "confirmed") return "st-confirmed";
    if (s === "conflict") return "st-conflict";
    return "st-inferred";
  }

  $effect(() => { load(); });
</script>

<div class="tab-panel">
  <div class="tab-header">
    <strong>Voices</strong>
    <button class="btn-small" onclick={load} disabled={loading} aria-label="Refresh voices" title="Refresh">R</button>
    <button class="btn-small" onclick={handleRecast} disabled={loading} aria-label="Recast unlocked" title="Recast unlocked">Recast</button>
  </div>
  {#if error}<p class="err">{error}</p>{/if}
  {#if loading}<p class="muted">loading...</p>{/if}
  {#each items as va}
    <div class="voice-row">
      <span class="char" title={va.character_id}>{va.character_id.replace("char_", "").slice(0, 14)}</span>
      <span class="vid" title={va.voice_id}>{va.voice_id.slice(0, 14)}</span>
      <span class="stat {statusClass(va.status)}" title={va.status}>{va.status}</span>
      {#if va.user_locked}
        <button class="btn-small" onclick={() => handleUnlock(va)} aria-label="Unlock voice" title="Unlock">U</button>
      {:else}
        <button class="btn-small" onclick={() => handleLock(va)} aria-label="Lock voice" title="Lock">L</button>
      {/if}
    </div>
  {/each}
  {#if items.length === 0 && !loading}
    <p class="muted">No assignments.</p>
  {/if}
</div>

<style>
  .tab-panel { font-size: 0.72rem; }
  .tab-header { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
  .err { color: #e53e3e; margin: 2px 0; }
  .muted { opacity: 0.6; margin: 2px 0; }
  .voice-row { display: flex; align-items: center; gap: 4px; padding: 2px 0; border-bottom: 1px solid var(--border); }
  .char { font-weight: 600; font-size: 0.7rem; min-width: 60px; }
  .vid { font-family: monospace; font-size: 0.6rem; opacity: 0.7; overflow: hidden; text-overflow: ellipsis; }
  .stat { font-size: 0.6rem; padding: 0 3px; border-radius: 2px; }
  .st-locked { background: #bee3f8; color: #2a4365; }
  .st-confirmed { background: #c6f6d5; color: #276749; }
  .st-conflict { background: #fed7d7; color: #9b2c2c; }
  .st-inferred { background: #edf2f7; color: #4a5568; }
  .btn-small { font-size: 0.6rem; padding: 0 4px; border: 1px solid var(--border); border-radius: 2px; background: var(--bg); color: var(--text); cursor: pointer; }
  .btn-small:hover { opacity: 0.8; }
</style>
