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

"""Universal Multi-Model Object Detector for Artemis."""

import asyncio
import base64
import json
import os
from pathlib import Path
import re

from langchain_core.messages import HumanMessage, ToolMessage

from artemis.llm.google import is_spatial_grounding_model
from artemis.llm.structured import ParseFailure, parse_structured
from artemis.services.llm import get_llm
from artemis.utils.logger import get_logger

logger = get_logger(__name__)

_DETECTOR_SEMAPHORE = asyncio.Semaphore(6)

#: Models already warned about, so a long run logs the caveat once per model.
_NON_SPATIAL_WARNED: set[str] = set()


def _warn_once_if_not_spatial(llm) -> None:
    """Warn when the detector model is not trained for coordinate localization.

    Point grounding is the one capability that does not transfer: a standard
    chat model returns a confident, wrong coordinate rather than an error, so
    the caller taps the wrong element. Silence here would make that
    indistinguishable from a working detector.
    """
    model_name = str(
        getattr(llm, "model_name", None)
        or getattr(llm, "model", None)
        or (getattr(llm, "endpoint", None) and getattr(llm.endpoint, "model_name", ""))
        or ""
    )
    if not model_name or model_name in _NON_SPATIAL_WARNED:
        return
    if is_spatial_grounding_model(model_name):
        return
    _NON_SPATIAL_WARNED.add(model_name)
    logger.warning(
        f"Object detection is running on {model_name!r}, which is not a Gemini ER "
        "(Embodied Reasoning) model. Returned coordinates will be approximate and "
        "may point at the wrong element. Prefer ARTEMIS_EXPLORER_VERSION=pro, whose "
        "grounding derives coordinates from real accessibility-tree bounds."
    )


async def _detect_single_label(
    llm,
    ctx,
    image_bytes,
    mime_type,
    label,
    templates,
    timeout_val=None,
) -> list[dict]:
    if timeout_val is None:
        timeout_val = float(os.environ.get("OBJECT_DETECTOR_TIMEOUT", "10.0"))

    img_b64 = base64.b64encode(image_bytes).decode("utf-8")

    for i, template in enumerate(templates):
        prompt = template.replace("{labels_str}", label)
        messages = [
            HumanMessage(
                content=[
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{img_b64}"},
                    },
                    {"type": "text", "text": prompt},
                ]
            )
        ]

        try:
            logger.info(f"Calling Object Detector for '{label}' (Attempt {i + 1})...")
            async with _DETECTOR_SEMAPHORE:
                response = await asyncio.wait_for(
                    llm.ainvoke(messages),
                    timeout=timeout_val,
                )

            output = response.content if isinstance(response.content, str) else ""
            if isinstance(response.content, list):
                output = "".join(
                    b.get("text", "")
                    for b in response.content
                    if isinstance(b, dict) and "text" in b
                )
            logger.info(f"Received response for '{label}' (Attempt {i + 1})")

            res_json = parse_structured(output)
            if isinstance(res_json, list):
                valid_results = []
                for item in res_json:
                    if isinstance(item, dict):
                        item["label"] = label
                        valid_results.append(item)
                return valid_results
            if isinstance(res_json, ParseFailure):
                logger.warning(
                    f"Object detector response for '{label}' was not valid"
                    f" JSON (attempt {i + 1}): {res_json.error}"
                )
            else:
                logger.warning(
                    f"Object detector response for '{label}' parsed to"
                    f" {type(res_json).__name__} instead of a list (attempt {i + 1})."
                )

        except Exception as e:
            logger.warning(f"Detection attempt {i + 1} failed for '{label}': {e}")

    return []


async def _run_object_detection(
    ctx,
    image_bytes: bytes | str | Path | None = None,
    queries: list[str] | None = None,
    templates: list[str] | None = None,
    mime_type: str = "image/jpeg",
    global_timeout: float = 30.0,
    image_path: str | Path | None = None,
) -> dict:
    target_img = image_bytes if image_bytes is not None else image_path
    if target_img is None:
        raise ValueError(
            "Either image_bytes or image_path must be provided to _run_object_detection"
        )
    if isinstance(target_img, (str, Path)):
        image_data = Path(target_img).read_bytes()
    else:
        image_data = target_img

    queries = queries or []
    templates = templates or ["Point to the following objects: {labels_str}"]
    # object_detector lives under `utils`, so it must be resolved as one:
    # without is_utils the lookup raises and every detection silently ran on the
    # operator's model, ignoring the configured (ER) detector entirely.
    try:
        llm = get_llm(ctx, name="object_detector", is_utils=True)
    except (ValueError, AttributeError, RuntimeError) as e:
        logger.debug(f"No object_detector configured ({e}); using the operator model.")
        llm = get_llm(ctx, name="operator")
    _warn_once_if_not_spatial(llm)

    raw_timeout = getattr(getattr(ctx, "llm_config", None), "timeout", None)
    if isinstance(raw_timeout, (int, float)):
        timeout_val = float(raw_timeout)
    else:
        timeout_val = float(os.environ.get("OBJECT_DETECTOR_TIMEOUT", "10.0"))

    tasks = [
        asyncio.create_task(
            _detect_single_label(
                llm,
                ctx,
                image_data,
                mime_type,
                label=query,
                templates=templates,
                timeout_val=timeout_val,
            )
        )
        for query in queries
    ]

    done, pending = await asyncio.wait(tasks, timeout=global_timeout)

    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    fused_results = []
    for task in done:
        try:
            res = task.result()
            if res:
                fused_results.extend(res)
        except Exception as e:
            logger.error(f"Task raised exception: {e}")

    # Swap coordinates from [y, x] normalized to [x, y] normalized if needed
    for item in fused_results:
        if (
            isinstance(item, dict)
            and "point" in item
            and isinstance(item["point"], list)
            and len(item["point"]) == 2
        ):
            y_norm, x_norm = item["point"]
            item["point"] = [x_norm, y_norm]

    detected_labels = set(
        item["label"] for item in fused_results if isinstance(item, dict) and "label" in item
    )
    failed_queries = [query for query in queries if query not in detected_labels]

    result_dict = {"detected": fused_results, "failed": failed_queries}

    if failed_queries:
        result_dict["message"] = (
            "Detection failed for some targets. Please try changing to a more"
            " detailed description (e.g., describe its shape, color, or nearby"
            " text)."
        )

    logger.info("Fused results from parallel inference.")
    return result_dict


async def _create_error_command(ctx, state, tool_call_id, error_message, wrapper):
    return ToolMessage(
        tool_call_id=tool_call_id or "default_tool_call",
        content=wrapper.on_failure_fn(error_message),
        additional_kwargs={"error": error_message},
        status="error",
    )


async def _create_success_command(ctx, state, tool_call_id, output, wrapper):
    return ToolMessage(
        tool_call_id=tool_call_id or "default_tool_call",
        content=wrapper.on_success_fn(output),
        status="success",
    )
