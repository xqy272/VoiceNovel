"""Tests for Harness Gate (expanded validators)."""

import pytest

from vn_core.contracts.reading_plan import ReadingPlanEntry, ReadingStyle
from vn_core.contracts.segment import Segment
from vn_core.contracts.timing_entry import TimingEntry
from vn_core.harness import GateDecision, HarnessGate
from vn_core.store import ProjectStore


@pytest.fixture
def gate():
    return HarnessGate()


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "harness_test.sqlite"
    s = ProjectStore(str(db_path))
    s.initialize()
    yield s
    s.close()


class TestSegmentValidation:
    def test_valid_segments(self, gate):
        segments = [
            Segment(segment_id="s001", paragraph_id="p001", source_order=0, text="Hello."),
            Segment(segment_id="s002", paragraph_id="p001", source_order=1, text="World."),
        ]
        result = gate.validate("segments", segments)
        assert result.decision == GateDecision.pass_decision

    def test_duplicate_segment_ids(self, gate):
        segments = [
            Segment(segment_id="s001", paragraph_id="p001", source_order=0, text="A."),
            Segment(segment_id="s001", paragraph_id="p001", source_order=1, text="B."),
        ]
        result = gate.validate("segments", segments)
        assert result.decision == GateDecision.fail_decision

    def test_empty_text(self, gate):
        segments = [
            Segment(segment_id="s001", paragraph_id="p001", source_order=0, text="  "),
        ]
        result = gate.validate("segments", segments)
        assert result.decision == GateDecision.fail_decision


class TestReadingPlanValidation:
    def test_valid_plan(self, gate):
        entries = [
            ReadingPlanEntry(
                segment_id="s001", text="Hello.",
                speaker_id="narrator", reading_style=ReadingStyle(),
            ),
        ]
        result = gate.validate("reading_plan", entries)
        assert result.decision == GateDecision.pass_decision

    def test_empty_text_in_plan(self, gate):
        entries = [
            ReadingPlanEntry(
                segment_id="s001", text="  ",
                speaker_id="narrator", reading_style=ReadingStyle(),
            ),
        ]
        result = gate.validate("reading_plan", entries)
        assert result.decision == GateDecision.fail_decision


class TestTimingValidation:
    def test_valid_timing(self, gate):
        entries = [
            TimingEntry(
                segment_id="s001", segmenter_version="v1",
                chapter_audio="ch01.mp3",
                start_ms=0, end_ms=1000, gap_after_ms=200,
            ),
            TimingEntry(
                segment_id="s002", segmenter_version="v1",
                chapter_audio="ch01.mp3",
                start_ms=1200, end_ms=2200, gap_after_ms=200,
            ),
        ]
        result = gate.validate("timing", entries)
        assert result.decision == GateDecision.pass_decision

    def test_overlapping_timing(self, gate):
        entries = [
            TimingEntry(
                segment_id="s001", segmenter_version="v1",
                chapter_audio="ch01.mp3",
                start_ms=0, end_ms=1500, gap_after_ms=200,
            ),
            TimingEntry(
                segment_id="s002", segmenter_version="v1",
                chapter_audio="ch01.mp3",
                start_ms=1200, end_ms=2200, gap_after_ms=200,
            ),
        ]
        result = gate.validate("timing", entries)
        assert result.decision == GateDecision.fail_decision


class TestAudioTakeValidation:
    def test_successful_audio_take_requires_audio_path(self, gate):
        result = gate.validate("audio_take", {"status": "success", "audio_path": ""})
        assert result.decision == GateDecision.retry_decision

    def test_failed_audio_take_does_not_require_audio_path(self, gate):
        result = gate.validate("audio_take", {"status": "failed", "audio_path": ""})
        assert result.decision == GateDecision.pass_decision


class TestHarnessCommit:
    def test_commit_artifact(self, gate, store):
        result = gate.commit(
            store=store,
            book_id="book01",
            artifact_type="segments",
            unit_id="ch001",
            artifact_version_id="seg_v001",
            input_hash="abc123",
        )
        assert result.decision == GateDecision.pass_decision
        artifact = store.get_active_artifact("book01", "segments", "ch001")
        assert artifact is not None

    def test_commit_writes_provenance(self, gate, store):
        gate.write_provenance(
            store=store,
            unit_id="ch001",
            stage="test_stage",
            artifact_version_id="test_v1",
        )
        conn = store._get_conn()
        row = conn.execute(
            "SELECT * FROM provenance WHERE unit_id='ch001'",
        ).fetchone()
        assert row is not None
        assert dict(row)["artifact_version_id"] == "test_v1"


class TestCommitStageResult:
    """Tests for HarnessGate.commit_stage_result() — the unified write path."""

    @pytest.fixture
    def gate(self):
        return HarnessGate()

    @pytest.fixture
    def store(self, tmp_path):
        db = tmp_path / "harness_csr.sqlite"
        s = ProjectStore(str(db))
        s.initialize()
        yield s
        s.close()

    def test_empty_artifact_version_id_fails(self, gate, store):
        from vn_core.contracts.stage_result import StageResult
        result = StageResult(
            stage="test", book_id="book_001", unit_id="ch001",
            proposed_artifacts=[{"artifact_type": "segments", "artifact_version_id": ""}],
        )
        r = gate.commit_stage_result(store, result)
        assert r.decision == GateDecision.fail_decision
        assert "Missing artifact_version_id" in r.reason

    def test_successful_commit_artifact_and_dependency(self, gate, store):
        from vn_core.contracts.stage_result import StageResult
        result = StageResult(
            stage="test", book_id="book_001", unit_id="ch001",
            proposed_artifacts=[{
                "artifact_type": "segments",
                "artifact_version_id": "book_001_segments_ch001_v001",
                "unit_id": "ch001",
                "data": [],
                "input_hash": "abc",
                "file_path": "/tmp/segs.jsonl",
            }],
            dependencies=[
                ("book_001_segments_ch001_v001", "book_001_import_ch001_v001", "derived"),
            ],
            provenance={
                "stage": "test", "unit_id": "ch001",
                "artifact_version_id": "book_001_segments_ch001_v001",
            },
        )
        # Write the dependency artifact first so it exists
        store.write_artifact("book_001", "book_001_import_ch001_v001", "import", "ch001")

        r = gate.commit_stage_result(store, result)
        assert r.decision == GateDecision.pass_decision, r.reason

        # Verify artifact was written
        active = store.get_active_artifact("book_001", "segments", "ch001")
        assert active is not None
        assert active["artifact_version_id"] == "book_001_segments_ch001_v001"

        # Verify dependency was recorded
        deps = store.get_artifact_dependencies("book_001", "book_001_segments_ch001_v001")
        assert len(deps) >= 1

        # Verify provenance was written
        conn = store._get_conn()
        prov_row = conn.execute(
            "SELECT * FROM provenance WHERE artifact_version_id='book_001_segments_ch001_v001'",
        ).fetchone()
        assert prov_row is not None

    def test_rollback_on_validation_failure(self, gate, store):
        """A second artifact with empty artifact_version_id should fail,
        and the first artifact should NOT be committed (rollback)."""
        from vn_core.contracts.stage_result import StageResult
        result = StageResult(
            stage="test", book_id="book_001", unit_id="ch001",
            proposed_artifacts=[
                {
                    "artifact_type": "segments",
                    "artifact_version_id": "rollback_test_v001",
                    "unit_id": "ch001",
                    "data": [],
                },
                {
                    "artifact_type": "timing",
                    "artifact_version_id": "",  # empty — should fail validation
                    "unit_id": "ch001",
                    "data": [],
                },
            ],
            provenance={"stage": "test", "unit_id": "ch001"},
        )
        r = gate.commit_stage_result(store, result)
        assert r.decision == GateDecision.fail_decision
        assert "Missing artifact_version_id" in r.reason

        # The first artifact should NOT exist — validation failure rolls back
        conn = store._get_conn()
        active = conn.execute(
            "SELECT * FROM artifacts WHERE artifact_version_id='rollback_test_v001'",
        ).fetchone()
        assert active is None, "First artifact should not exist after validation failure"

    def test_rollback_on_dependency_not_found(self, gate, store):
        """If a dependency doesn't exist, the entire stage should fail and rollback."""
        from vn_core.contracts.stage_result import StageResult
        result = StageResult(
            stage="test", book_id="book_001", unit_id="ch001",
            proposed_artifacts=[{
                "artifact_type": "segments",
                "artifact_version_id": "dep_fail_v001",
                "unit_id": "ch001",
                "data": [],
            }],
            dependencies=[
                ("dep_fail_v001", "nonexistent_dep_999", "depends"),
            ],
            provenance={"stage": "test", "unit_id": "ch001"},
        )
        r = gate.commit_stage_result(store, result)
        assert r.decision == GateDecision.fail_decision
        assert "not found" in r.reason.lower()

        # Verify artifact was not committed
        conn = store._get_conn()
        active = conn.execute(
            "SELECT * FROM artifacts WHERE artifact_version_id='dep_fail_v001'",
        ).fetchone()
        assert active is None, "Artifact should not exist after dependency validation failure"

    def test_decision_with_empty_segment_id_fails(self, gate, store):
        from vn_core.contracts.stage_result import StageResult
        result = StageResult(
            stage="test", book_id="book_001", unit_id="ch001",
            proposed_artifacts=[{
                "artifact_type": "reading_plan",
                "artifact_version_id": "rp_v1",
                "data": [],
            }],
            decisions=[{"segment_id": "", "decision_type": "speaker"}],
            provenance={"stage": "test", "artifact_version_id": "rp_v1"},
        )
        r = gate.commit_stage_result(store, result)
        assert r.decision == GateDecision.fail_decision
        assert "Decision missing segment_id" in r.reason

    def test_dependency_not_found_fails(self, gate, store):
        from vn_core.contracts.stage_result import StageResult
        result = StageResult(
            stage="test", book_id="book_001", unit_id="ch001",
            proposed_artifacts=[{
                "artifact_type": "reading_plan",
                "artifact_version_id": "rp_v2",
                "data": [],
            }],
            dependencies=[("rp_v2", "nonexistent_artifact", "depends")],
        )
        r = gate.commit_stage_result(store, result)
        assert r.decision == GateDecision.fail_decision
        assert "not found" in r.reason.lower()

    def test_provenance_without_artifact_version_id_uses_main(self, gate, store):
        from vn_core.contracts.stage_result import StageResult
        result = StageResult(
            stage="test", book_id="book_001", unit_id="ch001",
            proposed_artifacts=[{
                "artifact_type": "segments",
                "artifact_version_id": "main_vid_001",
                "data": [],
            }],
            provenance={"stage": "test", "unit_id": "ch001"},  # No artifact_version_id
        )
        r = gate.commit_stage_result(store, result)
        assert r.decision == GateDecision.pass_decision
        # Verify provenance used the main artifact's vid
        conn = store._get_conn()
        row = conn.execute(
            "SELECT artifact_version_id FROM provenance WHERE stage='test'",
        ).fetchone()
        assert row is not None
        assert row[0] == "main_vid_001"

    def test_commit_writes_exception(self, gate, store):
        gate.write_exception(
            store=store,
            book_id="book01",
            unit_id="ch001_s002",
            stage="tts_render",
            exception_type="tts_timeout",
            severity="high",
            message="TTS backend timed out",
        )
        rows = store._get_conn().execute(
            "SELECT * FROM exceptions WHERE book_id=?", ("book01",)
        ).fetchall()
        assert len(rows) >= 1
