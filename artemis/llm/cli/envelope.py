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

"""Tool-calling emulation for coding-agent CLI backends.

Neither ``claude -p`` nor ``codex exec`` exposes native function calling to
its caller: both run their own tool loop internally and hand back only a
final message.  ARTEMIS, however, drives every agent node through
``AIMessage.tool_calls``.

This module bridges the two by turning the bound tool schemas into a prompt
contract that asks for one JSON envelope, then parsing that envelope back
into LangChain tool calls:

.. code-block:: json

    {"thought": "...", "text": "...",
     "tool_calls": [{"name": "click", "args": {"index": 3}}]}

The parse reuses :mod:`artemis.llm.structured`, so fenced blocks, prose
padding, comments and trailing commas are all tolerated.  A reply that
carries no ``tool_calls`` is a legitimate text answer, not a failure - the
model is allowed to decline every tool.
"""

from __future__ import annotations

from typing import Any
import uuid

from langchain_core.messages import AIMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.utils.function_calling import convert_to_openai_tool

from artemis.llm.structured import ParseFailure, content_to_text, parse_structured
from artemis.utils.logger import get_logger

logger = get_logger(__name__)

#: Envelope keys. ``text`` carries the user-visible answer, ``thought`` an
#: optional rationale that ARTEMIS surfaces as a non-native thinking block.
ENVELOPE_TEXT_KEYS = ("text", "content", "message", "answer")
ENVELOPE_TOOL_KEYS = ("tool_calls", "toolCalls", "tools", "actions")


def normalize_tools(tools: Any) -> list[dict]:
    """Convert any LangChain-acceptable tool spec into OpenAI function dicts.

    ``convert_to_openai_tool`` already understands ``BaseTool``, pydantic
    models, plain callables and raw dicts, which is exactly the mix ARTEMIS
    nodes pass to ``bind_tools``.  Gemini-only builtin dicts (``google_search``
    and friends) carry no ``function_declarations`` and are dropped: a CLI
    backend cannot serve them.
    """
    normalized: list[dict] = []
    for tool in tools or []:
        if isinstance(tool, dict) and not tool.get("function") and "name" not in tool:
            # Provider-native builtin (e.g. {"google_search": {}}) - not portable.
            logger.debug(f"Dropping non-portable builtin tool spec for CLI backend: {list(tool)}")
            continue
        try:
            converted = convert_to_openai_tool(tool)
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            logger.warning(f"Could not convert tool {tool!r} for CLI backend: {e}")
            continue
        fn = converted.get("function") if isinstance(converted, dict) else None
        if isinstance(fn, dict) and fn.get("name"):
            normalized.append(fn)
    return normalized


def tool_names(tools: list[dict]) -> list[str]:
    return [t["name"] for t in tools if t.get("name")]


def build_tool_contract(tools: list[dict], *, args_as_string: bool = False) -> str:
    """Render the bound tools plus the response contract as prompt text.

    ``args_as_string`` selects the OpenAI-native wire shape, where each call
    carries ``arguments`` as a JSON-encoded string instead of an ``args``
    object.  Backends that hard-enforce a schema need it: OpenAI strict mode
    rejects a free-form object (every nested object must declare
    ``additionalProperties: false``, which a per-tool argument bag cannot).
    :func:`parse_envelope` accepts either shape.
    """
    if not tools:
        # No tools bound means the caller's own prompt defines the reply format -
        # the object detector asks for a JSON *list* of points, structured-output
        # callers name their own schema. Imposing an envelope here would fight
        # those instructions.
        return ""

    lines = [
        "## Available tools",
        "",
        "You can call the following tools. Each is described by its JSON Schema.",
        "",
    ]
    for fn in tools:
        name = fn.get("name", "")
        description = (fn.get("description") or "").strip()
        params = fn.get("parameters") or {"type": "object", "properties": {}}
        lines.append(f"### {name}")
        if description:
            lines.append(description)
        lines.append("Parameters (JSON Schema):")
        lines.append(_compact_json(params))
        lines.append("")

    if args_as_string:
        call_shape = (
            ' "tool_calls": [{"name": "<tool name>", "arguments": "<JSON-encoded'
            ' string of the arguments>"}]}'
        )
        args_rule = (
            "- `arguments` MUST be a JSON *string* (the encoded object), and the object"
            " it encodes MUST validate against that tool's JSON Schema."
        )
    else:
        call_shape = (
            ' "tool_calls": [{"name": "<tool name>", "args": {<arguments matching'
            " that tool's schema>}}]}"
        )
        args_rule = (
            "- `args` MUST be an object validating against that tool's JSON Schema."
            " Use the exact parameter names; do not invent parameters."
        )

    lines += [
        "## Response format",
        "",
        "Reply with a SINGLE JSON object and nothing else - no prose outside it, no",
        "markdown fences, no explanation before or after:",
        "",
        '{"thought": "<brief reasoning, optional>",',
        ' "text": "<message to the user, optional>",',
        call_shape,
        "",
        "Rules:",
        "- `name` MUST be one of: " + ", ".join(tool_names(tools)),
        args_rule,
        "- Emit multiple entries in `tool_calls` only when the tools are meant to run",
        "  back to back in that order.",
        "- Pass an empty `tool_calls` array when no tool should run, and answer in `text`.",
        "- Never wrap the JSON in ``` fences.",
    ]
    return "\n".join(lines)


def response_json_schema(tools: list[dict]) -> dict:
    """A strict JSON Schema for the envelope, for backends that enforce one.

    Codex accepts ``--output-schema``, which removes the parsing gamble
    entirely - but it is OpenAI strict mode, which demands that every object
    declare ``additionalProperties: false`` and list every property as
    required.  A per-tool argument bag cannot satisfy that, so ``arguments``
    is a JSON-encoded string here, exactly as in OpenAI's native
    function-calling wire format.  Per-tool argument schemas stay in the
    prompt contract, since one schema cannot express "arguments must match
    whichever tool `name` selects".
    """
    name_schema: dict[str, Any] = {"type": "string"}
    names = tool_names(tools)
    if names:
        name_schema["enum"] = names
    call_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"name": name_schema, "arguments": {"type": "string"}},
        "required": ["name", "arguments"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "thought": {"type": "string"},
            "text": {"type": "string"},
            "tool_calls": {"type": "array", "items": call_schema},
        },
        "required": ["thought", "text", "tool_calls"],
        "additionalProperties": False,
    }


def _compact_json(value: Any) -> str:
    import json

    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return str(value)


def _first_key(data: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def parse_envelope(
    raw: Any,
    *,
    allowed_names: list[str] | None = None,
    usage: UsageMetadata | None = None,
    response_metadata: dict[str, Any] | None = None,
) -> AIMessage:
    """Turn a CLI backend's final message into an ``AIMessage``.

    Falls back to treating the whole reply as plain text when it is not a
    JSON envelope: a model that answers in prose is answering, not failing.
    Tool calls naming a tool that was never bound are dropped with a warning
    rather than passed downstream, where they would raise deep inside the
    graph.
    """
    text = content_to_text(raw)
    parsed = parse_structured(text)

    thought = ""
    tool_calls: list[dict] = []
    if isinstance(parsed, ParseFailure) or not isinstance(parsed, dict):
        content = text.strip()
    else:
        content_value = _first_key(parsed, ENVELOPE_TEXT_KEYS)
        content = "" if content_value is None else str(content_value)
        thought_value = parsed.get("thought") or parsed.get("thinking") or parsed.get("reasoning")
        thought = "" if thought_value is None else str(thought_value)
        raw_calls = _first_key(parsed, ENVELOPE_TOOL_KEYS)
        if isinstance(raw_calls, dict):
            raw_calls = [raw_calls]
        for entry in raw_calls or []:
            call = _coerce_tool_call(entry, allowed_names)
            if call is not None:
                tool_calls.append(call)
        if not content and not tool_calls:
            # A JSON object that is neither envelope nor tool call (e.g. a
            # with_structured_output payload): hand the raw text back so the
            # caller can parse it against its own schema.
            content = text.strip()

    metadata = dict(response_metadata or {})
    if thought:
        metadata["cli_thought"] = thought

    return AIMessage(
        content=content,
        tool_calls=tool_calls,
        usage_metadata=usage,
        response_metadata=metadata,
    )


def _coerce_tool_call(entry: Any, allowed_names: list[str] | None) -> dict | None:
    if not isinstance(entry, dict):
        logger.warning(f"Ignoring non-object tool call from CLI backend: {entry!r}")
        return None
    name = entry.get("name") or entry.get("tool") or entry.get("function")
    if isinstance(name, dict):
        name = name.get("name")
    if not isinstance(name, str) or not name:
        logger.warning(f"Ignoring CLI tool call without a name: {entry!r}")
        return None
    if allowed_names and name not in allowed_names:
        logger.warning(
            f"CLI backend called unbound tool {name!r}; dropping it "
            f"(bound: {', '.join(allowed_names)})"
        )
        return None
    args = entry.get("args")
    if args is None:
        args = entry.get("arguments") or entry.get("parameters") or {}
    if isinstance(args, str):
        parsed_args = parse_structured(args)
        args = parsed_args if isinstance(parsed_args, dict) else {}
    if not isinstance(args, dict):
        logger.warning(f"Ignoring CLI tool call {name!r} with non-object args: {args!r}")
        return None
    return {
        "name": name,
        "args": args,
        "id": entry.get("id") or f"cli-{uuid.uuid4().hex[:12]}",
        "type": "tool_call",
    }


def build_structured_contract(schema: Any) -> str:
    """Render the response contract for a ``with_structured_output`` call.

    The caller validates the reply against ``schema``, so the model has to be
    told what that schema *is*. Promising only "reply with JSON" leaves the
    property names to the model's imagination: a run asking for
    ``ValidationResult{is_approved, feedback}`` kept getting
    ``{"approval": "approved", ...}`` back - the right judgment under names
    nothing downstream could parse. Backends that enforce the shape on the
    wire (Codex, via ``--output-schema``) never needed this; a prompt-contract
    backend does.
    """
    lines = [
        "## Response format",
        "Reply with a single JSON value and nothing else - no prose outside "
        "it, no markdown fences.",
    ]
    rendered = schema_as_json(schema)
    if rendered:
        lines += [
            "",
            "It must validate against this JSON Schema. Use exactly these"
            " property names - do not rename, add, or omit a required field:",
            rendered,
        ]
    return "\n".join(lines)


def schema_as_json(schema: Any) -> str | None:
    """Best-effort JSON Schema text for a pydantic model or a plain dict.

    Returns ``None`` when the schema cannot be rendered, so the caller can
    fall back to the bare JSON promise rather than fail the call.
    """
    if schema is None:
        return None
    if isinstance(schema, dict):
        return _compact_json(schema)
    builder = getattr(schema, "model_json_schema", None)
    if callable(builder):
        try:
            return _compact_json(builder())
        except Exception:  # pragma: no cover - exotic/partial schema objects
            return None
    return None
