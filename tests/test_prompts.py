"""Tests for LLM Prompt Registry."""

from __future__ import annotations

import pytest

from vn_core.prompts import PromptDefinition, PromptRegistry


class TestPromptDefinition:
    def test_render_system(self):
        d = PromptDefinition(
            name="test", version="1.0.0",
            system_template="Hello {name}",
        )
        assert d.render_system(name="World") == "Hello World"

    def test_render_user(self):
        d = PromptDefinition(
            name="test", version="1.0.0",
            user_template="Input: {input}",
        )
        assert d.render_user(input="test text") == "Input: test text"

    def test_empty_system_template(self):
        d = PromptDefinition(name="test", version="1.0.0")
        assert d.render_system() == ""


class TestPromptRegistry:
    @pytest.fixture
    def registry(self):
        r = PromptRegistry()
        return r

    def test_register_and_get(self, registry):
        d = PromptDefinition(name="test", version="1.0.0", description="test prompt")
        registry.register(d)
        got = registry.get("test")
        assert got is not None
        assert got.name == "test"
        assert got.version == "1.0.0"

    def test_get_latest_version(self, registry):
        registry.register(PromptDefinition(name="test", version="1.0.0"))
        registry.register(PromptDefinition(name="test", version="1.1.0"))
        registry.register(PromptDefinition(name="test", version="1.0.1"))
        got = registry.get("test")
        assert got.version == "1.1.0"

    def test_get_specific_version(self, registry):
        registry.register(PromptDefinition(name="test", version="1.0.0"))
        registry.register(PromptDefinition(name="test", version="2.0.0"))
        got = registry.get("test", "1.0.0")
        assert got is not None
        assert got.version == "1.0.0"

    def test_get_nonexistent(self, registry):
        assert registry.get("nonexistent") is None

    def test_duplicate_version_raises(self, registry):
        registry.register(PromptDefinition(name="test", version="1.0.0"))
        with pytest.raises(ValueError, match="immutable"):
            registry.register(PromptDefinition(name="test", version="1.0.0"))

    def test_list_prompts(self, registry):
        registry.register(PromptDefinition(name="b", version="1.0.0"))
        registry.register(PromptDefinition(name="a", version="1.0.0"))
        assert registry.list_prompts() == ["a", "b"]

    def test_list_versions(self, registry):
        registry.register(PromptDefinition(name="test", version="1.0.0"))
        registry.register(PromptDefinition(name="test", version="2.0.0"))
        assert registry.list_versions("test") == ["1.0.0", "2.0.0"]

    def test_load_builtins(self, registry):
        registry.load_builtins()
        names = registry.list_prompts()
        assert "character_extraction" in names
        assert "scene_summary" in names
        assert "speaker_attribution" in names
        assert "text_adaptation" in names

    def test_builtin_has_content(self, registry):
        registry.load_builtins()
        prompt = registry.get("character_extraction")
        assert prompt is not None
        assert "character" in prompt.system_template.lower()
        assert "JSON" in prompt.system_template

    def test_len(self, registry):
        registry.register(PromptDefinition(name="a", version="1.0.0"))
        registry.register(PromptDefinition(name="b", version="1.0.0"))
        registry.register(PromptDefinition(name="b", version="2.0.0"))
        assert len(registry) == 3


class TestLLMGatewayPromptIntegration:
    def test_build_from_prompt(self):
        from vn_core.llm_gateway import LLMGateway

        registry = PromptRegistry()
        registry.register(PromptDefinition(
            name="greeting",
            version="1.0.0",
            system_template="You are a helpful assistant.",
            user_template="Question: {question}",
        ))

        gateway = LLMGateway(prompt_registry=registry)
        request = gateway.build_from_prompt(
            "greeting",
            template_vars={"question": "What is the capital of France?"},
        )
        assert request is not None
        assert request.prompt_name == "greeting"
        assert request.prompt_version == "1.0.0"
        assert len(request.messages) == 2
        assert request.messages[0].role == "system"
        assert "helpful" in request.messages[0].content

    def test_build_from_prompt_includes_version_in_cache_key(self):
        from vn_core.llm_gateway import LLMGateway

        registry = PromptRegistry()
        registry.register(PromptDefinition(name="test", version="1.0.0", user_template="{input}"))

        gateway = LLMGateway(prompt_registry=registry)
        req1 = gateway.build_from_prompt("test", template_vars={"input": "hello"})
        registry.register(PromptDefinition(name="test", version="2.0.0", user_template="{input}"))
        req2 = gateway.build_from_prompt("test", template_vars={"input": "hello"})

        assert req1.compute_cache_key() != req2.compute_cache_key()

    def test_build_from_prompt_not_found(self):
        from vn_core.llm_gateway import LLMGateway

        gateway = LLMGateway()
        request = gateway.build_from_prompt("nonexistent")
        assert request is None

    def test_build_from_prompt_system_only(self):
        from vn_core.llm_gateway import LLMGateway

        registry = PromptRegistry()
        registry.register(PromptDefinition(
            name="sys_only",
            version="1.0.0",
            system_template="System: {info}",
            user_template="{input}",
        ))

        gateway = LLMGateway(prompt_registry=registry)
        request = gateway.build_from_prompt(
            "sys_only",
            template_vars={"info": "context", "input": "user text"},
        )
        assert len(request.messages) == 2
        assert request.messages[0].role == "system"
        assert request.messages[1].role == "user"
