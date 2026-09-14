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

"""Pointing a whole run at a different backend through an override file."""

import json

import pytest

from artemis.config.llm import (
    _expand_default_into_nodes,
    configured_override_path,
    normalize_override_dict,
    parse_llm_config,
)

_CLI_DEFAULT = {
    "provider": "claude_cli",
    "model": "sonnet",
    "fallback": {"provider": "claude_cli", "model": "haiku"},
}


def test_default_expands_into_every_required_node():
    expanded = _expand_default_into_nodes({"default": _CLI_DEFAULT})
    assert expanded["planner"]["provider"] == "claude_cli"
    assert expanded["utils"]["hopper"]["provider"] == "claude_cli"


def test_optional_nodes_are_honored_when_named():
    """Overrides for optional nodes used to be dropped on the floor."""
    expanded = _expand_default_into_nodes(
        {
            "default": _CLI_DEFAULT,
            "nodes": {"validator_pixel_safety_net": {"model": "haiku"}},
        }
    )
    assert expanded["validator_pixel_safety_net"]["provider"] == "claude_cli"
    assert expanded["validator_pixel_safety_net"]["model"] == "haiku"


def test_unnamed_optional_nodes_stay_unset():
    """Expanding 'default' into them would promote cheap judges to the flagship."""
    expanded = _expand_default_into_nodes({"default": _CLI_DEFAULT})
    assert "validator_pixel_safety_net" not in expanded
    assert "planner_validation" not in expanded


def test_node_overrides_merge_into_the_default_rather_than_replace_it():
    expanded = _expand_default_into_nodes(
        {
            "default": _CLI_DEFAULT,
            "nodes": {"object_detector": {"provider": "google", "model": "gemini-er"}},
        }
    )
    detector = expanded["utils"]["object_detector"]
    assert detector["provider"] == "google"
    # The nested fallback dict merges rather than being dropped.
    assert detector["fallback"]["provider"] == "claude_cli"


def test_normalize_expands_shorthand_but_leaves_explicit_form_alone():
    """An override file written in shorthand used to contribute nothing."""
    shorthand = normalize_override_dict({"default": _CLI_DEFAULT})
    assert shorthand["planner"]["provider"] == "claude_cli"

    explicit = {"planner": {"provider": "openai", "model": "gpt-4o"}}
    assert normalize_override_dict(explicit) == explicit


@pytest.mark.parametrize(
    "config_file",
    ["config/llm-config.claude-cli.jsonc", "config/llm-config.codex-cli.jsonc"],
)
def test_shipped_cli_configs_need_no_api_key_anywhere(monkeypatch, config_file):
    """Not one node may keep a keyed provider, primaries and fallbacks alike."""
    monkeypatch.setenv("ARTEMIS_LLM_CONFIG", config_file)
    cfg = parse_llm_config()

    assert configured_override_path() is not None
    expected = "claude_cli" if "claude" in config_file else "codex_cli"

    for name in (
        "planner",
        "operator",
        "checker",
        "explorer",
        "summarizer",
        "diagnoser",
        "log_analyzer",
    ):
        node = getattr(cfg, name)
        assert node.provider == expected, name
        assert node.fallback.provider == expected, name

    # Optional nodes must be remapped too, or they silently need a Google key.
    for name in (
        "history_analyzer",
        "validator_pixel_safety_net",
        "planner_validation",
        "output_analyzer",
    ):
        assert cfg.get_agent(name).provider == expected, name

    # object_detector included: it is the node that would otherwise hold the
    # only remaining Gemini key.
    for util in ("hopper", "outputter", "video_analyzer", "object_detector"):
        node = cfg.get_utils(util)
        assert node.provider == expected, util
        assert node.fallback.provider == expected, util


@pytest.mark.parametrize(
    "config_file",
    ["config/llm-config.claude-cli.jsonc", "config/llm-config.codex-cli.jsonc"],
)
def test_no_shipped_cli_node_points_at_a_keyed_provider(monkeypatch, config_file):
    """Belt and braces: sweep every node instead of naming them one by one."""
    from artemis.interfaces.cli.commands.doctor import _iter_llm_nodes

    monkeypatch.setenv("ARTEMIS_LLM_CONFIG", config_file)
    providers = {node.provider for _, node in _iter_llm_nodes(parse_llm_config())}
    assert providers <= {"claude_cli", "codex_cli"}, providers


def test_override_path_ignores_a_missing_file(monkeypatch, caplog):
    monkeypatch.setenv("ARTEMIS_LLM_CONFIG", "config/nope-not-here.jsonc")
    assert configured_override_path() is None


def test_absent_override_leaves_the_base_config_untouched(monkeypatch):
    monkeypatch.delenv("ARTEMIS_LLM_CONFIG", raising=False)
    monkeypatch.setattr("artemis.config.llm.settings.ARTEMIS_LLM_CONFIG", None)
    assert configured_override_path() is None
    assert parse_llm_config().planner.provider == "google"


def test_an_absolute_override_path_is_accepted(monkeypatch, tmp_path):
    override = tmp_path / "cli.json"
    override.write_text(json.dumps({"default": _CLI_DEFAULT}))
    monkeypatch.setenv("ARTEMIS_LLM_CONFIG", str(override))
    assert parse_llm_config().planner.provider == "claude_cli"
