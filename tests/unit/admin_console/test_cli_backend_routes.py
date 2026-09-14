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

"""The AI Model Setup screen's local-CLI backend endpoints."""

import os
import sys

import pytest

from apps.admin_console.routers import system as system_routes


#: Settings the endpoint under test writes straight into os.environ, so that a
#: task running in a separate worker sees them. monkeypatch cannot undo writes
#: it did not make, and a leaked ARTEMIS_LLM_CONFIG would silently re-point
#: every later test in the session at a CLI backend.
_LEAKY_ENV = ("ARTEMIS_LLM_CONFIG", "ARTEMIS_EXPLORER_VERSION")


@pytest.fixture
def env_file(monkeypatch, tmp_path):
    """Point .env writes at a scratch file, and hand back the process env."""
    target = tmp_path / ".env"
    # artemis.config re-exports the Settings *instance* as `settings`, which
    # shadows the submodule of the same name - `import artemis.config.settings
    # as m` binds the instance, since that form is an attribute lookup. Reach
    # the real module through sys.modules.
    settings_module = sys.modules["artemis.config.settings"]
    monkeypatch.setattr(settings_module, "get_env_file", lambda: target)

    from artemis.config.settings import settings

    saved_env = {name: os.environ.get(name) for name in _LEAKY_ENV}
    saved_attr = settings.ARTEMIS_LLM_CONFIG
    for name in _LEAKY_ENV:
        os.environ.pop(name, None)
    settings.ARTEMIS_LLM_CONFIG = None

    yield target

    for name, value in saved_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    settings.ARTEMIS_LLM_CONFIG = saved_attr


@pytest.fixture(autouse=True)
def no_readiness_rerun(monkeypatch):
    """The select endpoint re-runs every probe; that is not what is under test."""

    async def _run_all(*_args, **_kwargs):
        return {"probes": []}

    monkeypatch.setattr(system_routes.readiness_engine, "run_all", _run_all)
    monkeypatch.setattr(system_routes.readiness_engine, "invalidate_cache", lambda: None)


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_reports_both_backends_and_their_availability(monkeypatch, env_file):
    monkeypatch.setattr(
        "artemis.llm.cli.check_cli_backend",
        lambda provider: (provider == "claude_cli", f"reason for {provider}"),
    )
    payload = await system_routes.list_cli_backends()

    by_provider = {b["provider"]: b for b in payload["backends"]}
    assert set(by_provider) == {"claude_cli", "codex_cli"}
    assert by_provider["claude_cli"]["available"] is True
    assert by_provider["codex_cli"]["available"] is False
    assert by_provider["claude_cli"]["binary"] == "claude"
    # Nothing is selected until the user applies one.
    assert payload["active"] is None
    assert all(not b["active"] for b in payload["backends"])
    # The tier the caller must be told about, not left to discover.
    assert payload["explorer_version"] == "pro"


# ---------------------------------------------------------------------------
# Selecting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_selecting_writes_both_settings_to_env(monkeypatch, env_file):
    monkeypatch.setattr("artemis.llm.cli.check_cli_backend", lambda p: (True, "found"))

    result = await system_routes.select_cli_backend(
        system_routes.SelectCliBackendRequest(provider="claude_cli")
    )
    assert result["active"] == "claude_cli"

    written = env_file.read_text(encoding="utf-8")
    assert "ARTEMIS_LLM_CONFIG=config/llm-config.claude-cli.jsonc" in written
    # Not optional: the flash tier would ask this model for pixel coordinates.
    assert "ARTEMIS_EXPLORER_VERSION=pro" in written


@pytest.mark.asyncio
async def test_selection_is_visible_to_the_running_process(monkeypatch, env_file):
    """The worker reads env vars, so the select must take effect in-process."""
    monkeypatch.setattr("artemis.llm.cli.check_cli_backend", lambda p: (True, "found"))
    await system_routes.select_cli_backend(
        system_routes.SelectCliBackendRequest(provider="codex_cli")
    )

    from artemis.config.llm import configured_override_path

    override = configured_override_path()
    assert override is not None and "codex-cli" in str(override)
    assert (await system_routes.list_cli_backends())["active"] == "codex_cli"


@pytest.mark.asyncio
async def test_clearing_restores_the_stock_config(monkeypatch, env_file):
    monkeypatch.setattr("artemis.llm.cli.check_cli_backend", lambda p: (True, "found"))
    await system_routes.select_cli_backend(
        system_routes.SelectCliBackendRequest(provider="claude_cli")
    )

    result = await system_routes.select_cli_backend(
        system_routes.SelectCliBackendRequest(provider=None)
    )
    assert result["active"] is None

    from artemis.config.llm import configured_override_path

    assert configured_override_path() is None


@pytest.mark.asyncio
async def test_a_missing_binary_is_refused_rather_than_written(monkeypatch, env_file):
    monkeypatch.setattr(
        "artemis.llm.cli.check_cli_backend", lambda p: (False, "'claude' was not found on PATH")
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        await system_routes.select_cli_backend(
            system_routes.SelectCliBackendRequest(provider="claude_cli")
        )
    assert excinfo.value.status_code == 400
    assert "not found on PATH" in str(excinfo.value.detail)
    assert not env_file.exists() or "ARTEMIS_LLM_CONFIG=config" not in env_file.read_text()


@pytest.mark.asyncio
async def test_unknown_provider_is_rejected(env_file):
    from fastapi import HTTPException

    for provider in ("ollama", "google", "claude"):
        with pytest.raises(HTTPException) as excinfo:
            await system_routes.select_cli_backend(
                system_routes.SelectCliBackendRequest(provider=provider)
            )
        assert excinfo.value.status_code == 400


# ---------------------------------------------------------------------------
# The display cache
# ---------------------------------------------------------------------------


def test_every_loaded_module_variant_has_its_cache_cleared(monkeypatch):
    """This package is importable under two roots, each with its own class.

    Clearing only one leaves the other serving the previous model for the rest
    of its TTL, which is exactly the stale row the user would see after
    switching backends.
    """
    import sys
    import types

    variants = []
    for name in (
        "admin_console.services.model_service",
        "apps.admin_console.services.model_service",
    ):
        module = types.ModuleType(name)
        module.ModelService = type("ModelService", (), {"_llm_info_cache": ("stale",)})
        monkeypatch.setitem(sys.modules, name, module)
        variants.append(module.ModelService)

    system_routes._invalidate_model_display_cache()

    assert [v._llm_info_cache for v in variants] == [None, None]
