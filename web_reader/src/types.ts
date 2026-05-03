export interface TimingEntry {
  segment_id: string;
  segmenter_version: string;
  chapter_audio: string;
  start_ms: number;
  end_ms: number;
  gap_after_ms: number;
}

export interface SegmentData {
  segment_id: string;
  paragraph_id: string;
  source_order: number;
  text: string;
  quote_depth: number;
  is_dialogue_candidate: boolean;
}

export interface ReaderManifest {
  package_version: string;
  book_id: string;
  title: string;
  text_format: string;
  highlight_granularity: string;
  segmenter_version: string;
  audio_codec: string;
  segments: string;
  timing: string;
  audio_manifest: string;
  voices: string;
}

export interface ReaderAdapterResponse {
  book_id: string;
  status: string;
  current_chapter: string | null;
  available_chapters: string[];
  prefetch_status: Record<string, string>;
  manifest_url: string | null;
  chapter_content_url: string | null;
  chapter_audio_url: string | null;
  chapter_timing_url: string | null;
  error_message: string | null;
}

export interface ChapterInfo {
  chapter_id: string;
  title: string;
  paragraph_count: number;
}

export interface BookInfo {
  book_id: string;
  title?: string;
  chapters: ChapterInfo[];
}

export interface BakeResult {
  book_id: string;
  chapter_id: string;
  success: boolean;
  generation_config_id: string;
  reading_profile: string;
  package_dir: string;
  segment_count: number;
  timing_count: number;
  errors: string[];
}

export type PackageStatus = "ready" | "missing" | "invalid" | "stale";

export interface PackageInfo {
  status: PackageStatus;
  artifact_version_id: string;
  package_dir: string;
  dependency_ok: boolean;
  window_id?: string;
}

export interface JobRow {
  job_id: string;
  book_id?: string;
  job_kind?: "rebuild" | "prefetch" | "bake";
  status: string;
  priority?: string;
  stage?: string;
  cache_buster?: string;
  retry_count?: number;
  started_at?: string;
  finished_at?: string;
  last_error?: string;
  artifact?: string;
  unit_id?: string;
}

export interface ArtifactSummary {
  artifact_version_id: string;
  artifact_type?: string;
  unit_id?: string;
  status?: string;
  invalidated_reason?: string;
  file_path?: string;
  output_dir?: string;
}

export interface StationChapter {
  chapter_id: string;
  title: string;
  buffer: PackageInfo;
  full_package: PackageInfo;
  jobs: JobRow[];
  exceptions: Record<string, unknown>[];
  progress: {
    playable: boolean;
    full_ready: boolean;
    has_open_exceptions: boolean;
    needs_rebuild: boolean;
  };
  invalidated_artifacts: ArtifactSummary[];
}

export interface StationData {
  book_id: string;
  chapters: StationChapter[];
  queue: { pending: number; running: number; failed: number; done: number };
}

// -- Exception types --
export interface ExceptionEntry {
  exception_id: string;
  book_id: string;
  exception_type: string;
  severity: string;
  status: string;
  unit_id: string;
  stage: string;
  message: string;
  retry_count: number;
  created_at: string;
  resolved_at: string | null;
  details?: string;
}

export interface ExceptionListResponse {
  exceptions: ExceptionEntry[];
}

// -- Voice assignment types --
export interface VoiceAssignment {
  character_id: string;
  voice_id: string;
  confidence: number;
  user_locked: number;
  source: string;
  status: string;
  assigned_at?: string;
}

export interface VoiceAssignmentListResponse {
  book_id: string;
  assignments: VoiceAssignment[];
}

// -- Adaptation ops types --
export interface AdaptationOp {
  op_id: string;
  segment_id: string;
  original: string;
  normalized: string;
  category?: string;
  scope: string;
  confidence?: number;
  source?: string;
  evidence?: string[];
  risk?: string;
  rollback_reason?: string;
}

export interface AdaptationDecisionRow {
  book_id?: string;
  segment_id: string;
  decision_type: string;
  value: AdaptationOp;
  confidence?: number;
  source?: string;
  status?: string;
}

export interface AdaptationOpsResponse {
  book_id: string;
  chapter_id: string;
  ops: AdaptationDecisionRow[];
}

export interface ReplayResponse {
  text: string;
  warnings: string[];
}

export interface DiffResponse {
  before: string;
  after: string;
  changes: Record<string, unknown>[];
}

export interface RollbackResponse {
  book_id: string;
  chapter_id: string;
  artifact_version_id: string;
  rolled_back_op_ids: string[];
  new_op_count: number;
  warnings: string[];
}

export interface BufferResponse {
  book_id: string;
  chapter_id: string;
  status: string;
  package_kind: string;
  package_dir: string;
  artifact_version_id: string;
  content_url: string;
  audio_url: string;
  timing_url: string;
  manifest_url: string;
}
