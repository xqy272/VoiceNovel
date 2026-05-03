"""Pipeline module: end-to-end orchestration of audiobook generation."""

from vn_core.pipeline.pipeline import BakeResult, ColdStartResult, Pipeline

__all__ = ["Pipeline", "BakeResult", "ColdStartResult"]
