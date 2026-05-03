"""Harness Gate: schema validation, invariant checks, and quality gates."""

from __future__ import annotations

import hashlib
import json
import os as _os
from dataclasses import dataclass
from enum import Enum
from typing import Any

from vn_core.contracts.exception_entry import (
    ExceptionEntry,
)
from vn_core.contracts.exception_entry import (
    ExceptionSeverity as ExceptionSeverity,
)
from vn_core.contracts.exception_entry import (
    ExceptionStatus as ExceptionStatus,
)
from vn_core.contracts.exception_entry import (
    ExceptionType as ExceptionType,
)


class GateDecision(str, Enum):
    pass_decision = "pass"
    retry_decision = "retry"
    fail_decision = "fail"
    stale_decision = "stale"


@dataclass
class GateResult:
    decision: GateDecision
    reason: str = ""
    exceptions: list[ExceptionEntry] | None = None


class HarnessGate:
    def validate(
        self,
        artifact_type: str,
        proposed_data: Any,
        context: dict | None = None,
    ) -> GateResult:
        validators = {
            "segments": self._validate_segments,
            "reading_plan": self._validate_reading_plan,
            "audio_take": self._validate_audio_take,
            "timing": self._validate_timing,
            "reader_package": self._validate_reader_package,
            "paragraph_integrity": self._validate_paragraph_integrity,
            "source_anchor": self._validate_source_anchor,
            "manifest_consistency": self._validate_manifest_consistency,
        }

        validator = validators.get(artifact_type)
        if validator:
            return validator(proposed_data, context or {})

        return GateResult(
            decision=GateDecision.pass_decision,
            reason=f"No specific validator for {artifact_type}"
        )

    def _validate_segments(self, data: Any, context: dict) -> GateResult:
        from vn_core.contracts.segment import Segment

        if isinstance(data, list):
            segments = data
        elif isinstance(data, dict) and "segments" in data:
            segments = data["segments"]
        else:
            return GateResult(
                decision=GateDecision.fail_decision,
                reason="Invalid segments data format"
            )

        for i, seg in enumerate(segments):
            if not isinstance(seg, Segment):
                continue
            if not seg.text.strip():
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=f"Empty text in segment {seg.segment_id}",
                )

        seen_ids = set()
        for seg in segments:
            if not isinstance(seg, Segment):
                continue
            if seg.segment_id in seen_ids:
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=f"Duplicate segment_id: {seg.segment_id}",
                )
            seen_ids.add(seg.segment_id)

        return GateResult(decision=GateDecision.pass_decision)

    def _validate_reading_plan(self, data: Any, context: dict) -> GateResult:
        from vn_core.contracts.reading_plan import ReadingPlanEntry

        if isinstance(data, list):
            entries = data
        elif isinstance(data, dict) and "plan" in data:
            entries = data["plan"]
        else:
            return GateResult(
                decision=GateDecision.pass_decision,
                reason="No reading plan data to validate",
            )

        for entry in entries:
            if not isinstance(entry, ReadingPlanEntry):
                continue
            if not entry.segment_id.strip():
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason="Empty segment_id in reading plan entry",
                )
            if not entry.text.strip():
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=f"Empty text in reading plan for {entry.segment_id}",
                )

        return GateResult(decision=GateDecision.pass_decision)

    def _validate_audio_take(self, data: Any, context: dict) -> GateResult:
        if isinstance(data, dict):
            if data.get("status") == "success" and not data.get("audio_path"):
                return GateResult(
                    decision=GateDecision.retry_decision,
                    reason="Audio take missing audio_path",
                )
        return GateResult(decision=GateDecision.pass_decision)

    def _validate_timing(self, data: Any, context: dict) -> GateResult:
        from vn_core.contracts.timing_entry import TimingEntry

        if isinstance(data, list):
            entries = data
        elif isinstance(data, dict) and "timing" in data:
            entries = data["timing"]
        else:
            return GateResult(
                decision=GateDecision.pass_decision,
                reason="No timing data to validate",
            )

        prev_end = 0
        for entry in entries:
            if not isinstance(entry, TimingEntry):
                continue
            if entry.start_ms < prev_end:
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=f"Timing overlap at {entry.segment_id}: "
                    f"start_ms={entry.start_ms} < prev_end={prev_end}",
                )
            prev_end = entry.end_ms

        return GateResult(decision=GateDecision.pass_decision)

    def _validate_reader_package(self, data: Any, context: dict) -> GateResult:
        from pathlib import Path

        if not isinstance(data, dict):
            return GateResult(
                decision=GateDecision.fail_decision,
                reason="Invalid reader_package data format",
            )

        package_dir = Path(data.get("package_dir", ""))
        require_audio = bool(data.get("require_audio", True))
        required_files = [
            "manifest.json",
            "cleaned.html",
            "segments.jsonl",
            "voices.json",
            "timing.json",
        ]
        if require_audio:
            required_files.append("audio_manifest.json")

        for filename in required_files:
            if not (package_dir / filename).exists():
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=f"Reader package missing {filename}",
                )

        if require_audio:
            audio_dir = package_dir / "audio"
            if not audio_dir.exists():
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason="Reader package missing audio directory",
                )
            if not any(audio_dir.glob("*.wav")) and not any(audio_dir.glob("*.mp3")):
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason="Reader package missing chapter audio",
                )

        return GateResult(decision=GateDecision.pass_decision)

    @staticmethod
    def _validate_paragraph_integrity(data: Any, context: dict) -> GateResult:
        """Check that all source paragraphs are represented and in order."""
        from vn_core.contracts.segment import Segment

        segments: list = []
        if isinstance(data, list):
            segments = data
        elif isinstance(data, dict):
            segments = data.get("segments", data.get("data", []))
        if not segments:
            return GateResult(decision=GateDecision.pass_decision)

        # Collect paragraph IDs in original order
        para_order: list[str] = []
        seen_paras = set()
        for seg in segments:
            pid = seg.paragraph_id if isinstance(seg, Segment) else seg.get("paragraph_id", "")
            if pid and pid not in seen_paras:
                para_order.append(pid)
                seen_paras.add(pid)

        # Verify paragraphs appear in source_order
        source_orders: dict[str, int] = {}
        for seg in segments:
            pid = seg.paragraph_id if isinstance(seg, Segment) else seg.get("paragraph_id", "")
            order = seg.source_order if isinstance(seg, Segment) else seg.get("source_order", -1)
            if pid and order >= 0:
                if pid in source_orders:
                    if source_orders[pid] != order:
                        return GateResult(
                            decision=GateDecision.fail_decision,
                            reason=f"Inconsistent source_order for paragraph {pid}",
                        )
                source_orders[pid] = order

        # Check that paragraph orders are monotonic
        sorted_paras = sorted(source_orders.items(), key=lambda x: x[1])
        for i, (pid, order) in enumerate(sorted_paras):
            expected = sorted_paras[0][1] + i
            if order != expected:
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=(
                        f"Gap in paragraph source_order: "
                        f"expected {expected}, got {order} for {pid}"
                    ),
                )

        return GateResult(decision=GateDecision.pass_decision)

    @staticmethod
    def _validate_source_anchor(data: Any, context: dict) -> GateResult:
        """Check that all items carry source_href for traceability."""
        items: list = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("segments", data.get("plan", data.get("data", [])))
        if not items:
            return GateResult(decision=GateDecision.pass_decision)

        missing = []
        for item in items:
            href = getattr(item, "source_href", None)
            if href is None and isinstance(item, dict):
                href = item.get("source_href", "")
            if not href:
                sid = (
                    getattr(item, "segment_id", "")
                    if hasattr(item, "segment_id")
                    else item.get("segment_id", "?")
                )
                missing.append(sid)

        if missing:
            return GateResult(
                decision=GateDecision.fail_decision,
                reason=f"{len(missing)} items missing source_href, first: {missing[:3]}",
            )
        return GateResult(decision=GateDecision.pass_decision)

    @staticmethod
    def _validate_manifest_consistency(data: Any, context: dict) -> GateResult:
        """Check that manifest, timing, and audio_manifest reference the same chapters."""
        if not isinstance(data, dict):
            return GateResult(decision=GateDecision.pass_decision)

        manifest_codec = data.get("manifest_codec", "")
        timing_file = data.get("timing_file", "")

        # If manifest says mp3 but timing references .wav, flag it
        if manifest_codec and timing_file:
            if manifest_codec == "mp3" and timing_file.endswith(".wav"):
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=f"Manifest codec={manifest_codec} but timing references {timing_file}",
                )
            if manifest_codec == "wav" and timing_file.endswith(".mp3"):
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=f"Manifest codec={manifest_codec} but timing references {timing_file}",
                )

        return GateResult(decision=GateDecision.pass_decision)

    # ------------------------------------------------------------------
    # Activation transaction
    # ------------------------------------------------------------------

    def activate_artifact(
        self,
        store: Any,
        book_id: str,
        artifact_version_id: str,
    ) -> GateResult:
        """Activate an artifact atomically: validate deps → supersede → activate → provenance.

        All steps run inside a single transaction so partial state is impossible.
        Returns GateResult with pass_decision on success.
        """
        conn = store._get_conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM artifacts WHERE book_id=? AND artifact_version_id=?",
                (book_id, artifact_version_id),
            ).fetchone()
            if not row:
                conn.rollback()
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=f"Artifact not found: {artifact_version_id}",
                )
            art = dict(row)

            dep_check = store.check_dependencies_active(book_id, artifact_version_id)
            if not dep_check["all_active"]:
                inactive = [d["depends_on_artifact_version_id"] for d in dep_check["inactive"]]
                conn.rollback()
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=f"{len(inactive)} dependencies not active: {inactive[:3]}",
                )

            conn.execute(
                """UPDATE artifacts SET status='superseded'
                WHERE book_id=? AND artifact_type=? AND unit_id=? AND status='active'
                AND artifact_version_id != ?""",
                (book_id, art["artifact_type"], art["unit_id"], artifact_version_id),
            )
            conn.execute(
                "UPDATE artifacts SET status='active' WHERE book_id=? AND artifact_version_id=?",
                (book_id, artifact_version_id),
            )
            try:
                metadata = json.loads(art.get("metadata") or "{}")
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            self.write_provenance(
                store=store,
                unit_id=art["unit_id"],
                stage="artifact_activation",
                artifact_version_id=artifact_version_id,
                generation_config_id=metadata.get("generation_config_id", ""),
                commit=False,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            return GateResult(
                decision=GateDecision.fail_decision,
                reason="Activation transaction failed",
            )

        return GateResult(decision=GateDecision.pass_decision, reason="activated")

    # ------------------------------------------------------------------
    # Stage result commit (unified write path)
    # ------------------------------------------------------------------

    def commit_stage_result(
        self,
        store: Any,
        result: Any,  # StageResult
    ) -> GateResult:
        """Commit a StageResult atomically in a single transaction.

        All writes (artifacts, dependencies, decisions, memory patches,
        exceptions, provenance) happen inside one ``BEGIN IMMEDIATE`` /
        ``COMMIT`` boundary. No intermediate commits.
        """
        from vn_core.contracts.stage_result import StageResult

        if not isinstance(result, StageResult):
            return GateResult(
                decision=GateDecision.fail_decision,
                reason="Expected StageResult",
            )

        # 1. Validate each proposed artifact (read-only before transaction)
        main_artifact_vid = ""
        for art in result.proposed_artifacts:
            art_type = art.get("artifact_type", "")
            vid = art.get("artifact_version_id", "")
            if not vid:
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=f"Missing artifact_version_id for {art_type}",
                )
            if not main_artifact_vid:
                main_artifact_vid = vid
            validation = self.validate(art_type, art.get("data"), {})
            if validation.decision == GateDecision.fail_decision:
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=f"{art_type} validation failed: {validation.reason}",
                )

        # Validate dependency references exist and are active
        for dep in result.dependencies:
            dep_vid = dep[1]  # depends_on_artifact_version_id
            conn_chk = store._get_conn()
            dep_row = conn_chk.execute(
                "SELECT status FROM artifacts WHERE book_id=? AND artifact_version_id=?",
                (result.book_id, dep_vid),
            ).fetchone()
            if not dep_row:
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=f"Dependency artifact not found: {dep_vid}",
                )
            if dep_row[0] != "active":
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=f"Dependency artifact not active: {dep_vid} (status={dep_row[0]})",
                )

        # Validate provenance: if artifacts exist, provenance needs artifact_version_id
        if result.provenance and not result.provenance.get("artifact_version_id"):
            if main_artifact_vid:
                result.provenance["artifact_version_id"] = main_artifact_vid
            elif not result.proposed_artifacts and result.memory_patches:
                # Allow provenance without artifact when only memory patches exist
                # (e.g., scanner results)
                pass
            else:
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason="Provenance missing artifact_version_id and no main artifact",
                )

        # Validate decisions have required fields
        for dec in result.decisions:
            if not dec.get("segment_id"):
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason="Decision missing segment_id",
                )

        # Validate memory patches have required identifiers
        for patch in result.memory_patches:
            ptype = patch.get("type", "")
            if ptype == "character" and not patch.get("character_id"):
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason="Memory patch type=character missing character_id",
                )
            if ptype == "voice_assignment" and not patch.get("character_id"):
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason="Memory patch type=voice_assignment missing character_id",
                )

        # 2. Single transaction: all writes at once.
        #    Artifact data files are written atomically with the DB:
        #    temp → DB rows (pointing to final path) → os.replace() → DB commit.
        #    If os.replace fails: DB rollback, temp cleaned, no final file.
        #    If DB commit  fails: DB rollback, temp + any replaced finals cleaned.
        import json as _json
        import re as _re
        import uuid as _uuid

        conn = store._get_conn()
        staged_files: list[tuple[str, str]] = []  # (tmp_path, final_path)

        # Compute safe data directory: always relative to the store's db_path
        raw_db = getattr(store, "db_path", ".")
        data_dir = _os.path.abspath(
            _os.path.join(_os.path.dirname(_os.path.abspath(str(raw_db))), "artifact_data"),
        )
        _os.makedirs(data_dir, exist_ok=True)

        replaced_finals: list[str] = []
        try:
            # --- Phase 1: write temp files (before DB transaction) ---
            for art in result.proposed_artifacts:
                vid = art.get("artifact_version_id", "")
                if art.get("data") and not art.get("file_path", ""):
                    safe_name = _re.sub(r"[^a-zA-Z0-9_.-]", "_", vid) + ".json"
                    final_fpath = _os.path.abspath(_os.path.join(data_dir, safe_name))
                    if not final_fpath.startswith(data_dir + _os.sep):
                        return GateResult(
                            decision=GateDecision.fail_decision,
                            reason=f"Artifact data path escape: {safe_name}",
                        )
                    tmp_fpath = final_fpath + ".tmp"
                    with open(tmp_fpath, "w", encoding="utf-8") as f:
                        _json.dump(art["data"], f, ensure_ascii=False, indent=2)
                    staged_files.append((tmp_fpath, final_fpath))

            # --- Phase 2: DB transaction ---
            conn.execute("BEGIN IMMEDIATE")

            for art in result.proposed_artifacts:
                vid = art.get("artifact_version_id", "")
                atype = art["artifact_type"]
                uid = art.get("unit_id", result.unit_id)
                file_path = art.get("file_path", "")
                metadata = dict(art.get("metadata", {}))

                # Map data-backed artifacts to their final file paths
                if art.get("data") and not file_path:
                    safe_name = _re.sub(r"[^a-zA-Z0-9_.-]", "_", vid) + ".json"
                    file_path = _os.path.abspath(_os.path.join(data_dir, safe_name))
                    metadata["data_key"] = safe_name

                # Supersede old active
                conn.execute(
                    """UPDATE artifacts SET status='superseded'
                    WHERE book_id=? AND artifact_type=? AND unit_id=? AND status='active'
                    AND artifact_version_id != ?""",
                    (result.book_id, atype, uid, vid),
                )
                # Insert new active
                conn.execute(
                    """INSERT OR REPLACE INTO artifacts
                    (book_id, artifact_version_id, artifact_type, unit_id,
                     schema_version, input_hash, status, file_path, metadata)
                    VALUES (?, ?, ?, ?, '0.1', ?, 'active', ?, ?)""",
                    (result.book_id, vid, atype, uid,
                     art.get("input_hash", ""),
                     file_path,
                     _json.dumps(metadata)),
                )

            # Dependencies
            for dep in result.dependencies:
                conn.execute(
                    """INSERT OR REPLACE INTO artifact_dependencies
                    (book_id, artifact_version_id, depends_on_artifact_version_id,
                     dependency_role)
                    VALUES (?, ?, ?, ?)""",
                    (result.book_id, dep[0], dep[1],
                     dep[2] if len(dep) > 2 else ""),
                )

            # Memory patches
            for patch in result.memory_patches:
                ptype = patch.get("type", "")
                if ptype == "character":
                    conn.execute(
                        """INSERT OR REPLACE INTO characters
                        (book_id, character_id, names, aliases, traits, first_seen,
                         assigned_voice_id, confidence, status, evidence, created_by, run_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (result.book_id, patch.get("character_id", ""),
                         _json.dumps(patch.get("names", [])),
                         _json.dumps(patch.get("aliases", [])),
                         _json.dumps(patch.get("traits", [])),
                         patch.get("first_seen", ""),
                         patch.get("assigned_voice_id", ""),
                         patch.get("confidence", 1.0),
                         patch.get("status", "inferred"),
                         _json.dumps(patch.get("evidence", [])),
                         patch.get("created_by", ""),
                         patch.get("run_id", "")),
                    )
                elif ptype == "voice_assignment":
                    conn.execute(
                        """INSERT OR REPLACE INTO voice_assignments
                        (book_id, character_id, voice_id, confidence, user_locked,
                         source, status)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (result.book_id, patch.get("character_id", ""),
                         patch.get("voice_id", ""),
                         patch.get("confidence", 1.0),
                         int(patch.get("user_locked", False)),
                         patch.get("source", "auto"),
                         patch.get("status", "inferred")),
                    )
                elif ptype == "glossary":
                    conn.execute(
                        """INSERT OR REPLACE INTO glossary
                        (book_id, term, definition, category,
                         pronunciation, confidence, status, created_by)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (result.book_id, patch.get("term", ""),
                         patch.get("definition", ""),
                         patch.get("category", ""),
                         patch.get("pronunciation", ""),
                         patch.get("confidence", 0.7),
                         patch.get("status", "inferred"),
                         patch.get("created_by", "scanner")),
                    )

            # Decisions
            for dec in result.decisions:
                conn.execute(
                    """INSERT OR REPLACE INTO decisions
                    (book_id, segment_id, decision_type, value, confidence, status,
                     user_locked, source, evidence, created_by, run_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (result.book_id, dec.get("segment_id", ""),
                     dec.get("decision_type", ""),
                     _json.dumps(dec.get("value", {})),
                     dec.get("confidence", 1.0),
                     "inferred", 0,
                     dec.get("source", "auto"),
                     _json.dumps(dec.get("evidence", [])),
                     dec.get("created_by", ""),
                     dec.get("run_id", "")),
                )

            # Exceptions
            for exc in result.exceptions:
                conn.execute(
                    """INSERT INTO exceptions
                    (exception_id, book_id, exception_type, severity,
                     status, unit_id, stage, message, details)
                    VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
                    (f"exc_{_uuid.uuid4().hex[:12]}",
                     result.book_id,
                     exc.get("exception_type", "schema_error"),
                     exc.get("severity", "medium"),
                     exc.get("unit_id", result.unit_id),
                     exc.get("stage", result.stage),
                     exc.get("message", ""),
                     _json.dumps(exc.get("details", {})),
                     ),
                )

            # Provenance
            if result.provenance:
                conn.execute(
                    """INSERT INTO provenance
                    (unit_id, stage, generation_config_id, artifact_version_id,
                     llm_model, input_hash, output_hash, run_id, reading_profile)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (result.provenance.get("unit_id", result.unit_id),
                     result.provenance.get("stage", result.stage),
                     result.provenance.get("generation_config_id", ""),
                     result.provenance.get("artifact_version_id", ""),
                     result.provenance.get("llm_model", ""),
                     result.provenance.get("input_hash", ""),
                     result.provenance.get("output_hash", ""),
                     result.provenance.get("run_id", ""),
                     result.provenance.get("reading_profile", "enhanced")),
                )

            # --- Phase 3: atomically move temp files to final paths BEFORE DB commit.
            #    If any replace fails, rollback DB, clean up, and return failure.
            replaced_finals: list[str] = []
            for tmp_path, final_path in staged_files:
                try:
                    _os.replace(tmp_path, final_path)
                    replaced_finals.append(final_path)
                except OSError as re:
                    # Roll back DB, remove any already-replaced finals + all temps
                    conn.execute("ROLLBACK")
                    for fpath in replaced_finals:
                        try:
                            _os.remove(fpath)
                        except OSError:
                            pass
                    for tpath, _ in staged_files:
                        try:
                            if _os.path.exists(tpath):
                                _os.remove(tpath)
                        except OSError:
                            pass
                    return GateResult(
                        decision=GateDecision.fail_decision,
                        reason=f"Artifact data file replace failed: {re}",
                    )

            # --- Phase 4: commit DB ---
            conn.commit()
            return GateResult(decision=GateDecision.pass_decision, reason="committed")

        except Exception as e:
            # DB or pre-DB failure — rollback + clean up everything
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            for fpath in replaced_finals:
                try:
                    _os.remove(fpath)
                except OSError:
                    pass
            for tmp_path, _ in staged_files:
                try:
                    if _os.path.exists(tmp_path):
                        _os.remove(tmp_path)
                except OSError:
                    pass

            return GateResult(
                decision=GateDecision.fail_decision,
                reason=f"Transaction failed: {e}",
            )

    # ------------------------------------------------------------------
    # Voice Assignment commit helper
    # ------------------------------------------------------------------

    def commit_voice_assignments(
        self,
        store: Any,
        book_id: str,
        unit_id: str,
        assignments: list[dict],
        generation_config_id: str = "",
        artifact_version_id: str | None = None,
    ) -> GateResult:
        """Commit voice assignments through the Harness Gate.

        Each assignment dict must have: ``character_id``, ``voice_id``.
        Optional: ``confidence``, ``status``, ``user_locked``, ``source``.

        If ``artifact_version_id`` is provided it is used as the artifact
        version; otherwise the next version is computed from the Store.

        Writes a ``voice_assignment`` artifact + provenance in one transaction.
        """
        if not assignments:
            return GateResult(decision=GateDecision.pass_decision, reason="no assignments")

        from vn_core.contracts.stage_result import StageResult

        for a in assignments:
            if not a.get("character_id"):
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason="Voice assignment missing character_id",
                )
            if not a.get("voice_id"):
                return GateResult(
                    decision=GateDecision.fail_decision,
                    reason=f"Voice assignment missing voice_id for {a.get('character_id')}",
                )

        if artifact_version_id:
            vid = artifact_version_id
        else:
            conn = store._get_conn()
            row = conn.execute(
                """SELECT COUNT(*) FROM artifacts
                WHERE book_id=? AND artifact_type=? AND unit_id=?""",
                (book_id, "voice_assignment", unit_id),
            ).fetchone()
            counter = (row[0] + 1) if row else 1
            vid = f"{book_id}_voice_assignment_{unit_id}_v{counter:03d}"

        result = StageResult(
            stage="voice_casting",
            book_id=book_id,
            unit_id=unit_id,
            proposed_artifacts=[{
                "artifact_type": "voice_assignment",
                "artifact_version_id": vid,
                "unit_id": unit_id,
                "data": assignments,
                "input_hash": hashlib.sha256(
                    json.dumps(
                        sorted(assignments, key=lambda x: x.get("character_id", "")),
                        ensure_ascii=False,
                    ).encode("utf-8"),
                ).hexdigest()[:40],
            }],
            memory_patches=[
                {
                    "type": "voice_assignment",
                    "character_id": a["character_id"],
                    "voice_id": a["voice_id"],
                    "confidence": a.get("confidence", 1.0),
                    "user_locked": a.get("user_locked", False),
                    "status": a.get("status", "inferred"),
                    "source": a.get("source", "auto"),
                }
                for a in assignments
            ],
            provenance={
                "stage": "voice_casting",
                "unit_id": unit_id,
                "artifact_version_id": vid,
                "generation_config_id": generation_config_id,
            },
        )
        return self.commit_stage_result(store, result)

    # ------------------------------------------------------------------
    # Scanner commit helper
    # ------------------------------------------------------------------

    def commit_scan_result(
        self,
        store: Any,
        book_id: str,
        unit_id: str,
        characters: list[dict] | None = None,
        glossary_terms: list[dict] | None = None,
        generation_config_id: str = "",
    ) -> GateResult:
        """Commit scanner results through the Harness Gate.

        ``characters`` and ``glossary_terms`` are converted to
        ``memory_patches`` and submitted as a ``StageResult`` in one
        transaction.  At least one of *characters* or *glossary_terms*
        must be provided.
        """
        if not characters and not glossary_terms:
            return GateResult(
                decision=GateDecision.pass_decision, reason="empty scan result",
            )

        from vn_core.contracts.stage_result import StageResult

        patches: list[dict] = []
        if characters:
            for c in characters:
                if not c.get("name"):
                    return GateResult(
                        decision=GateDecision.fail_decision,
                        reason="Character patch missing name",
                    )
                char_id = c.get("character_id") or f"char_{c['name']}"
                patches.append({
                    "type": "character",
                    "character_id": char_id,
                    "names": c.get("names", [c["name"]]),
                    "aliases": c.get("aliases", []),
                    "traits": c.get("traits", []),
                    "first_seen": c.get("first_seen", unit_id),
                    "assigned_voice_id": c.get("assigned_voice_id", ""),
                    "confidence": c.get("confidence", 0.7),
                    "status": c.get("status", "inferred"),
                    "evidence": c.get("evidence", []),
                    "created_by": "scanner",
                    "run_id": c.get("run_id", ""),
                })

        if glossary_terms:
            for g in glossary_terms:
                if not g.get("term"):
                    continue
                patches.append({
                    "type": "glossary",
                    "term": g["term"],
                    "definition": g.get("definition", ""),
                    "category": g.get("category", ""),
                    "pronunciation": g.get("pronunciation", ""),
                    "confidence": g.get("confidence", 0.7),
                    "created_by": "scanner",
                })

        if not patches:
            return GateResult(
                decision=GateDecision.pass_decision, reason="no valid scan patches",
            )

        result = StageResult(
            stage="scanner",
            book_id=book_id,
            unit_id=unit_id,
            memory_patches=patches,
            provenance={
                "stage": "scanner",
                "unit_id": unit_id,
                "generation_config_id": generation_config_id,
            },
        )
        return self.commit_stage_result(store, result)

    # ------------------------------------------------------------------
    # Write gate
    # ------------------------------------------------------------------

    def commit(
        self,
        store: Any,
        book_id: str,
        artifact_type: str,
        unit_id: str,
        artifact_version_id: str,
        file_path: str = "",
        input_hash: str = "",
        metadata: dict | None = None,
    ) -> GateResult:
        store.write_artifact(
            book_id=book_id,
            artifact_version_id=artifact_version_id,
            artifact_type=artifact_type,
            unit_id=unit_id,
            file_path=file_path,
            input_hash=input_hash,
            metadata=metadata,
        )
        return GateResult(
            decision=GateDecision.pass_decision,
            reason=f"Committed {artifact_type} for {unit_id}",
        )

    def write_provenance(
        self,
        store: Any,
        unit_id: str,
        stage: str,
        artifact_version_id: str,
        llm_model: str = "",
        generation_config_id: str = "",
        input_hash: str = "",
        output_hash: str = "",
        run_id: str = "",
        reading_profile: str = "enhanced",
        commit: bool = True,
    ):
        store._get_conn().execute(
            """INSERT INTO provenance
            (unit_id, stage, generation_config_id, artifact_version_id, llm_model,
             input_hash, output_hash, run_id, reading_profile)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                unit_id,
                stage,
                generation_config_id,
                artifact_version_id,
                llm_model,
                input_hash,
                output_hash,
                run_id,
                reading_profile,
            ),
        )
        if commit:
            store._get_conn().commit()

    def write_exception(
        self,
        store: Any,
        book_id: str,
        unit_id: str,
        stage: str,
        exception_type: str,
        severity: str = "medium",
        message: str = "",
        details: dict | None = None,
    ):
        import uuid
        store._get_conn().execute(
            """INSERT INTO exceptions
            (exception_id, book_id, exception_type, severity,
             status, unit_id, stage, message, details)
            VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)""",
            (
                f"exc_{uuid.uuid4().hex[:12]}",
                book_id,
                exception_type,
                severity,
                unit_id,
                stage,
                message,
                json.dumps(details or {}),
            ),
        )
        store._get_conn().commit()

    def write_decision(
        self,
        store: Any,
        book_id: str,
        segment_id: str,
        decision_type: str,
        value: dict,
        confidence: float = 1.0,
        source: str = "auto",
        evidence: list[str] | None = None,
    ):
        store.upsert_decision(
            book_id=book_id,
            segment_id=segment_id,
            decision_type=decision_type,
            value=value,
            confidence=confidence,
            source=source,
            evidence=evidence,
        )
