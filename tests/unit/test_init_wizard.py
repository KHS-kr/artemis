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

"""What `artemis init` writes into .env for each provider choice."""

import pytest

from artemis.interfaces.cli.commands import init as init_module


@pytest.fixture
def run_wizard(monkeypatch, tmp_path):
    """Drive the wizard with scripted answers and capture the generated .env."""
    env_path = tmp_path / ".env"
    monkeypatch.setattr(init_module, "get_env_file", lambda: env_path)
    # Device scan and MCP install both reach outside the process.
    monkeypatch.setattr(init_module.shutil, "which", lambda _: None)

    def _run(provider_choice: str, api_key: str = "sk-test-key") -> str:
        answers = iter([provider_choice, api_key, "8"])

        def fake_ask(*_args, **_kwargs):
            return next(answers)

        monkeypatch.setattr(init_module.Prompt, "ask", fake_ask)
        init_module.init_command()
        return env_path.read_text(encoding="utf-8")

    return _run


def test_api_key_provider_writes_its_own_key_and_model(run_wizard):
    env = run_wizard("3")
    assert "ANTHROPIC_API_KEY=sk-test-key" in env
    # The model line used to say gemini-2.5-flash whichever provider you picked.
    assert "ARTEMIS_DEFAULT_MODEL=claude-sonnet-5" in env
    assert "gemini" not in env.lower()
    assert "ARTEMIS_LLM_CONFIG" not in env


def test_gemini_choice_is_unchanged(run_wizard):
    env = run_wizard("1")
    assert "GEMINI_API_KEY=sk-test-key" in env
    assert "ARTEMIS_DEFAULT_MODEL=gemini-2.5-flash" in env
    assert "ARTEMIS_DEFAULT_PROFILE=pro" in env


@pytest.mark.parametrize(
    "choice, config_file, model",
    [
        ("5", "config/llm-config.claude-cli.jsonc", "sonnet"),
        ("6", "config/llm-config.codex-cli.jsonc", "gpt-5.5"),
    ],
)
def test_cli_backend_needs_no_key_and_selects_its_config(run_wizard, choice, config_file, model):
    env = run_wizard(choice)

    # No API key is collected, so none may be written.
    assert "sk-test-key" not in env
    assert f"ARTEMIS_LLM_CONFIG={config_file}" in env
    assert f"ARTEMIS_DEFAULT_MODEL={model}" in env
    # A CLI call pays process startup every step; Flash is the sane default.
    assert "ARTEMIS_DEFAULT_PROFILE=flash" in env
    # A CLI backend needs no provider key at all, so none may be suggested.
    assert "GEMINI_API_KEY" not in env
    # The Explorer's flash tier is the one path that would still want a Gemini
    # ER model, so the tier that works without one is pinned explicitly.
    assert "ARTEMIS_EXPLORER_VERSION=pro" in env


def test_generated_env_parses_as_key_value_lines(run_wizard):
    for choice in ("1", "5"):
        for line in run_wizard(choice).splitlines():
            if line and not line.startswith("#"):
                assert "=" in line, line
