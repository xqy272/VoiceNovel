"""Tests for JSON Schema and TypeScript export from contracts."""

import json
from pathlib import Path

from vn_core.contracts.export_schema import generate_json_schemas, generate_typescript_types


class TestJSONSchemaExport:
    def test_generate_schemas(self):
        schemas = generate_json_schemas()
        assert len(schemas) >= 18
        assert "Segment" in schemas
        assert "ReadingPlanEntry" in schemas
        assert "TimingEntry" in schemas
        assert "VoiceAssignment" in schemas
        assert "BackendSpeechRequest" in schemas
        assert "GenerationConfig" in schemas

    def test_schema_has_properties(self):
        schemas = generate_json_schemas()
        seg_schema = schemas["Segment"]
        assert "properties" in seg_schema
        assert "segment_id" in seg_schema["properties"]
        assert "text" in seg_schema["properties"]

    def test_schema_required_fields(self):
        schemas = generate_json_schemas()
        seg_schema = schemas["Segment"]
        assert "required" in seg_schema
        assert "segment_id" in seg_schema["required"]

    def test_write_schemas_to_disk(self, tmp_path):
        generate_json_schemas(output_dir=str(tmp_path / "schemas"))
        assert (tmp_path / "schemas" / "Segment.json").exists()
        assert (tmp_path / "schemas" / "contracts.json").exists()
        content = json.loads((tmp_path / "schemas" / "Segment.json").read_text())
        assert "properties" in content

    def test_generate_typescript_types(self, tmp_path):
        output = str(tmp_path / "types.ts")
        ts = generate_typescript_types(output_path=output)
        assert "export interface Segment" in ts
        assert "export interface TimingEntry" in ts
        assert "export interface VoiceAssignment" in ts
        assert "export interface GenerationConfig" in ts
        assert (Path(output)).exists()
