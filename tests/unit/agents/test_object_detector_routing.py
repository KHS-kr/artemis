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

"""Which model object detection actually runs on."""

import types

import pytest

from artemis.config.llm import parse_llm_config
from artemis.services.llm import _resolve_endpoint


@pytest.fixture
def ctx():
    return types.SimpleNamespace(llm_config=parse_llm_config(), data_engine=None)


def test_object_detector_resolves_as_a_utils_node(ctx):
    """It lives under `utils`, so resolving it as an agent node raises.

    That is what used to happen: the caller's broad `except` swallowed the
    AttributeError and every detection silently ran on the operator's model,
    ignoring the configured ER detector.
    """
    endpoint = _resolve_endpoint(ctx, "object_detector", is_utils=True)
    assert "robotics-er" in endpoint.model_name

    with pytest.raises(AttributeError):
        _resolve_endpoint(ctx, "object_detector", is_utils=False)


def test_the_default_config_does_not_detect_with_the_operator_model(ctx):
    detector = _resolve_endpoint(ctx, "object_detector", is_utils=True)
    operator = _resolve_endpoint(ctx, "operator", is_utils=False)
    assert detector.model_name != operator.model_name


def test_detection_falls_back_to_the_operator_when_unconfigured(ctx):
    """An unset detector is legitimate - it must degrade, not crash."""
    ctx.llm_config.utils.object_detector = None
    with pytest.raises(ValueError):
        _resolve_endpoint(ctx, "object_detector", is_utils=True)
    assert _resolve_endpoint(ctx, "operator", is_utils=False).model_name


def test_a_cli_backed_detector_is_flagged_as_non_spatial(monkeypatch):
    """The warning is the only signal that coordinates became guesses."""
    from artemis.agents.object_detector import object_detector as od

    monkeypatch.setattr(od, "_NON_SPATIAL_WARNED", set())
    warnings: list[str] = []
    monkeypatch.setattr(od.logger, "warning", lambda msg: warnings.append(str(msg)))

    od._warn_once_if_not_spatial(types.SimpleNamespace(model_name="sonnet"))
    od._warn_once_if_not_spatial(types.SimpleNamespace(model_name="sonnet"))
    assert len(warnings) == 1
    assert "not a Gemini ER" in warnings[0]
    assert "ARTEMIS_EXPLORER_VERSION=pro" in warnings[0]

    od._warn_once_if_not_spatial(types.SimpleNamespace(model_name="gemini-robotics-er-2-preview"))
    assert len(warnings) == 1
