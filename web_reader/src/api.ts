import type {
  AdaptationOpsResponse,
  BakeResult,
  BookInfo,
  BufferResponse,
  DiffResponse,
  ExceptionListResponse,
  ReaderAdapterResponse,
  ReaderManifest,
  ReplayResponse,
  RollbackResponse,
  StationData,
  TimingEntry,
  VoiceAssignment,
  VoiceAssignmentListResponse,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE || "";

export function resolveApiUrl(url: string): string {
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) return url;
  if (url.startsWith("/")) return `${API_BASE}${url}`;
  return `${API_BASE}/${url}`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = "";
    try {
      const payload = await res.json();
      detail = payload.detail ? `: ${payload.detail}` : "";
    } catch {
      detail = "";
    }
    throw new Error(`API error ${res.status}${detail}`);
  }
  return res.json();
}

export async function listProjects(): Promise<BookInfo[]> {
  return request<BookInfo[]>("/api/projects");
}

export async function getProject(bookId: string): Promise<BookInfo> {
  return request<BookInfo>(`/api/projects/${bookId}`);
}

export async function createProject(
  sourcePath: string,
  bookId: string
): Promise<BookInfo> {
  return request<BookInfo>("/api/projects", {
    method: "POST",
    body: JSON.stringify({
      source_path: sourcePath,
      book_id: bookId,
    }),
  });
}

export async function listChapters(
  bookId: string
): Promise<{ chapter_id: string; title: string }[]> {
  return request(`/api/projects/${bookId}/chapters`);
}

export async function getReaderStatus(
  bookId: string,
  chapterId?: string
): Promise<ReaderAdapterResponse> {
  return request<ReaderAdapterResponse>("/api/reader-adapter", {
    method: "POST",
    body: JSON.stringify({
      book_id: bookId,
      chapter_id: chapterId || null,
      action: "get_status",
    }),
  });
}

export async function getChapterContent(
  bookId: string,
  chapterId: string
): Promise<ReaderAdapterResponse> {
  return request<ReaderAdapterResponse>("/api/reader-adapter", {
    method: "POST",
    body: JSON.stringify({
      book_id: bookId,
      chapter_id: chapterId,
      action: "get_chapter",
      capabilities: ["highlight", "audio_stream"],
    }),
  });
}

export async function bakeChapter(
  bookId: string,
  chapterId: string
): Promise<BakeResult> {
  return request<BakeResult>("/api/bake", {
    method: "POST",
    body: JSON.stringify({
      book_id: bookId,
      chapter_id: chapterId,
    }),
  });
}

export async function fetchManifest(url: string): Promise<ReaderManifest> {
  const res = await fetch(url);
  return res.json();
}

export async function fetchTiming(url: string): Promise<TimingEntry[]> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Timing not available: ${res.status}`);
  return res.json();
}

export function chapterHtmlUrl(bookId: string, chapterId: string): string {
  return `${API_BASE}/api/projects/${bookId}/chapters/${chapterId}/content`;
}

export function chapterAudioUrl(bookId: string, chapterId: string): string {
  return `${API_BASE}/api/projects/${bookId}/chapters/${chapterId}/audio`;
}

export async function getBuffer(
  bookId: string,
  chapterId: string,
): Promise<BufferResponse> {
  return request<BufferResponse>(
    `/api/projects/${bookId}/chapters/${chapterId}/buffer`,
  );
}

export async function getStation(bookId: string): Promise<StationData> {
  return request<StationData>(`/api/projects/${bookId}/station`);
}

export async function retryJob(jobId: string): Promise<{ job_id: string; status: string; ok: boolean }> {
  return request(`/api/jobs/${jobId}/retry`, { method: "POST" });
}

export async function cancelJob(jobId: string): Promise<{ job_id: string; status: string; cancelled: boolean; ok: boolean }> {
  return request(`/api/jobs/${jobId}/cancel`, { method: "POST" });
}

export async function coldStartChapter(bookId: string, chapterId: string): Promise<Record<string, unknown>> {
  return request(`/api/projects/${bookId}/chapters/${chapterId}/cold-start`, { method: "POST" });
}

export async function exportChapter(
  bookId: string, chapterId: string, format: string,
): Promise<{ book_id: string; chapter_id: string; format: string; artifact_version_id: string; output_dir: string }> {
  return request(
    `/api/projects/${bookId}/chapters/${chapterId}/exports?format=${format}`,
    { method: "POST" },
  );
}

export function exportDownloadUrl(bookId: string, artifactVersionId: string): string {
  const safeBook = encodeURIComponent(bookId);
  const safeVid = encodeURIComponent(artifactVersionId);
  return `${API_BASE}/api/projects/${safeBook}/exports/${safeVid}/download`;
}

export async function listExports(
  bookId: string,
  chapterId?: string,
  format?: string,
  status?: string,
): Promise<{ book_id: string; exports: Record<string, unknown>[] }> {
  const params = new URLSearchParams();
  if (chapterId) params.set("chapter_id", chapterId);
  if (format) params.set("format", format);
  if (status) params.set("status", status);
  const qs = params.toString();
  return request(`/api/projects/${bookId}/exports${qs ? `?${qs}` : ""}`);
}

export interface PreflightResult {
  ok: boolean;
  operation: string;
  book_id: string;
  chapter_id: string;
  checks: { name: string; status: string; message: string }[];
  blocking_errors: string[];
  warnings: string[];
  estimated_cost: {
    segment_count_est: number;
    tts_total_chars: number;
    total_duration_minutes: number;
    llm_cost_usd: number;
    tts_cost_usd: number;
    total_cost_usd: number;
  } | null;
}

export async function preflightChapter(
  bookId: string, chapterId: string,
  operation: string = "bake",
  generationConfigId: string = "default",
  format?: string,
): Promise<PreflightResult> {
  return request(`/api/projects/${bookId}/chapters/${chapterId}/preflight`, {
    method: "POST",
    body: JSON.stringify({
      operation,
      generation_config_id: generationConfigId,
      format: format || "daw",
    }),
  });
}

export async function rebuildChapter(
  bookId: string, chapterId: string,
): Promise<{ job_id: string; status: string; duplicate: boolean }> {
  return request(`/api/projects/${bookId}/chapters/${chapterId}/rebuild`, { method: "POST" });
}

export async function resolveException(exceptionId: string): Promise<{ exception_id: string; status: string }> {
  return request(`/api/exceptions/${exceptionId}/resolve`, { method: "POST" });
}

export async function listExceptions(
  bookId: string, status?: string, unitId?: string,
): Promise<ExceptionListResponse> {
  const params = new URLSearchParams();
  if (bookId) params.set("book_id", bookId);
  if (status) params.set("status", status);
  if (unitId) params.set("unit_id", unitId);
  return request(`/api/exceptions?${params.toString()}`);
}

export async function listVoiceAssignments(bookId: string): Promise<VoiceAssignmentListResponse> {
  return request(`/api/projects/${bookId}/voice-assignments`);
}

export async function lockVoiceAssignment(
  bookId: string, characterId: string, voiceId: string,
): Promise<{ book_id: string; character_id: string; locked: boolean; status: string }> {
  return request(`/api/projects/${bookId}/voice-assignments/lock`, {
    method: "POST",
    body: JSON.stringify({ character_id: characterId, voice_id: voiceId }),
  });
}

export async function unlockVoiceAssignment(
  bookId: string, characterId: string,
): Promise<{ book_id: string; character_id: string; locked: boolean; status: string }> {
  return request(`/api/projects/${bookId}/voice-assignments/unlock`, {
    method: "POST",
    body: JSON.stringify({ character_id: characterId }),
  });
}

export async function recastUnlockedVoiceAssignments(
  bookId: string,
): Promise<{ book_id: string; updated_count: number; updated: VoiceAssignment[] }> {
  return request(`/api/projects/${bookId}/voice-assignments/recast-unlocked`, {
    method: "POST",
  });
}

export async function listAdaptationOps(
  bookId: string, chapterId: string, segmentId?: string,
): Promise<AdaptationOpsResponse> {
  const qs = segmentId ? `?segment_id=${encodeURIComponent(segmentId)}` : "";
  return request(`/api/projects/${bookId}/chapters/${chapterId}/adaptation-ops${qs}`);
}

export async function replayAdaptationOps(
  bookId: string, chapterId: string,
  sourceText: string, ops: Record<string, unknown>[], scope?: string,
): Promise<ReplayResponse> {
  return request(`/api/projects/${bookId}/chapters/${chapterId}/adaptation-ops/replay`, {
    method: "POST",
    body: JSON.stringify({ source_text: sourceText, ops, scope }),
  });
}

export async function diffAdaptationText(
  bookId: string, chapterId: string,
  before: string, after: string,
): Promise<DiffResponse> {
  return request(`/api/projects/${bookId}/chapters/${chapterId}/adaptation-ops/diff`, {
    method: "POST",
    body: JSON.stringify({ before, after }),
  });
}

export async function rollbackAdaptationOps(
  bookId: string, chapterId: string,
  opIds: string[], reason: string,
): Promise<RollbackResponse> {
  return request(`/api/projects/${bookId}/chapters/${chapterId}/adaptation-ops/rollback`, {
    method: "POST",
    body: JSON.stringify({ op_ids: opIds, reason }),
  });
}

export async function prefetchChapter(
  bookId: string,
  currentChapterId: string,
): Promise<{
  prefetch_chapters: string[];
  hot_window_before: string[];
  hot_window_after: string[];
  enqueued_jobs: { chapter_id: string; job_id: string }[];
  queue_depth: number;
}> {
  return request(`/api/projects/${bookId}/prefetch`, {
    method: "POST",
    body: JSON.stringify({
      book_id: bookId,
      current_chapter_id: currentChapterId,
    }),
  });
}
