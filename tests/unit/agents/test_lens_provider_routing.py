# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Which provider the background lenses actually build.

The Flash step summarizer and the transcript capsule compressor carry their own
model name in the *agent* config (`agent.flash.step_summarizer.model`,
`agent.memory.chunking.model`). Those names predate multi-provider support and
are Gemini names, so a lens that treats "a model name is configured" as "build a
Google client" pins the whole run to Gemini - and kills it outright when no
Google key exists.
"""

import types

import pytest

from artemis.config.llm import parse_llm_config


@pytest.fixture
def cli_ctx(monkeypatch):
    """A context whose LLM config routes every node to the Claude CLI."""
    monkeypatch.setenv("ARTEMIS_LLM_CONFIG", "config/llm-config.claude-cli.jsonc")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from artemis.config.settings import settings

    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    return types.SimpleNamespace(llm_config=parse_llm_config(), data_engine=None, session_id="test")


@pytest.fixture
def gemini_ctx(monkeypatch):
    """A context on the stock Gemini config."""
    monkeypatch.delenv("ARTEMIS_LLM_CONFIG", raising=False)
    from artemis.config.settings import settings

    monkeypatch.setattr(settings, "ARTEMIS_LLM_CONFIG", None)
    return types.SimpleNamespace(llm_config=parse_llm_config(), data_engine=None, session_id="test")


def _model_name(llm) -> str:
    for attr in ("model_name", "model"):
        value = getattr(llm, attr, None)
        if isinstance(value, str) and value:
            return value
    return ""


def _is_google(llm) -> bool:
    return (
        "Google" in type(getattr(llm, "base_model", llm)).__name__ or "Google" in type(llm).__name__
    )


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------


def test_lens_override_applies_on_a_google_node(gemini_ctx):
    """A Gemini model name means something on a Gemini endpoint: honor it.

    Asserted on the resolved endpoint rather than a built client, so the test
    needs no Google credentials.
    """
    from artemis.services.llm import resolve_lens_endpoint

    endpoint = resolve_lens_endpoint(
        gemini_ctx, "summarizer", model_override="gemini-3.5-flash-lite"
    )
    assert endpoint.provider == "google"
    assert endpoint.model_name == "gemini-3.5-flash-lite"


def test_lens_override_is_ignored_on_a_non_google_node(cli_ctx):
    """The node's own provider wins; a Gemini name cannot be served by a CLI."""
    from artemis.services.llm import get_lens_llm, resolve_lens_endpoint

    endpoint = resolve_lens_endpoint(cli_ctx, "summarizer", model_override="gemini-3.5-flash-lite")
    assert endpoint.provider == "claude_cli"
    assert endpoint.model_name == cli_ctx.llm_config.summarizer.model

    llm = get_lens_llm(cli_ctx, "summarizer", model_override="gemini-3.5-flash-lite")
    assert not _is_google(llm)
    assert "gemini" not in _model_name(llm).lower()


def test_lens_resolves_the_summarizer_as_an_agent_node(cli_ctx):
    """`summarizer` lives on LLMConfig, not LLMConfigUtils.

    Looked up as a utils node it raises AttributeError, which a broad `except`
    turned into a silent fall-through to a hardcoded Gemini client.
    """
    from artemis.services.llm import get_lens_llm

    llm = get_lens_llm(cli_ctx, "summarizer")
    assert _model_name(llm) == cli_ctx.llm_config.summarizer.model


# ---------------------------------------------------------------------------
# The Flash step summarizer
# ---------------------------------------------------------------------------


def test_step_summarizer_builds_without_a_google_key(cli_ctx):
    """This is the failure that killed a real run before step 1."""
    from artemis.agents.flash.summarizer import VisualStepSummarizer

    summarizer = VisualStepSummarizer(cli_ctx, model_name="gemini-3.5-flash-lite")
    assert not _is_google(summarizer._llm)


def test_step_summarizer_without_an_override_uses_the_configured_node(cli_ctx):
    from artemis.agents.flash.summarizer import VisualStepSummarizer

    summarizer = VisualStepSummarizer(cli_ctx, model_name=None)
    assert not _is_google(summarizer._llm)
    assert summarizer._model_name == cli_ctx.llm_config.summarizer.model


def test_the_knob_still_selects_the_model_on_a_gemini_config(gemini_ctx):
    """No regression for existing Gemini users: the override still applies."""
    from artemis.services.llm import resolve_lens_endpoint

    for knob in ("gemini-3.5-flash-lite", "gemini-3.8-flash"):
        endpoint = resolve_lens_endpoint(gemini_ctx, "summarizer", model_override=knob)
        assert endpoint.provider == "google"
        assert endpoint.model_name == knob


def test_the_lens_model_is_raw_so_it_meters_itself(cli_ctx):
    """Lens prompts are metered with update_last_prompt=False.

    Wrapping them in the gateway would meter at the wrapper exit instead, and a
    tiny lens prompt would become the compaction thresholds' live context base.
    """
    from artemis.services.llm import RobustChatModelWrapper, get_lens_llm

    assert not isinstance(get_lens_llm(cli_ctx, "summarizer"), RobustChatModelWrapper)


# ---------------------------------------------------------------------------
# The transcript capsule compressor
# ---------------------------------------------------------------------------


def test_capsule_lens_builds_without_a_google_key(cli_ctx):
    """Same defect, later trigger: this one fires once L2 chunking kicks in."""
    from artemis.memory.chunking import StepCapsuleLens

    lens = StepCapsuleLens(model_name="gemini-3.8-flash", ctx=cli_ctx)
    assert not _is_google(lens._get_llm())
