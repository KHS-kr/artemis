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

"""Coding-agent CLI backends: envelope, history folding and process shaping.

The CLIs themselves are never spawned here - :meth:`build_invocation` and
:meth:`parse_output` are pure, so the argv, the stdin payload and the parse of
a recorded transcript are all checkable without a subscription.
"""

import base64
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
import pytest

from artemis.llm.cli import (
    ChatClaudeCLI,
    ChatCodexCLI,
    CLIInvocationError,
    build_tool_contract,
    normalize_tools,
    parse_envelope,
    render_messages,
    response_json_schema,
)
from artemis.llm.reliability import FailureCategory, classify_failure
from artemis.llm.router import ModelFactory, ModelEndpoint, ModelProvider

_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()


@tool
def click_element(index: int, reason: str) -> str:
    """Tap the element at a numeric index.

    Args:
        index: Index of the element.
        reason: Why it is tapped.
    """
    return "ok"


# ---------------------------------------------------------------------------
# Provider routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("claude_cli", ModelProvider.CLAUDE_CLI),
        ("claude-cli", ModelProvider.CLAUDE_CLI),
        ("claudecode", ModelProvider.CLAUDE_CLI),
        ("codex_cli", ModelProvider.CODEX_CLI),
        ("codex", ModelProvider.CODEX_CLI),
        ("CODEX-CLI", ModelProvider.CODEX_CLI),
    ],
)
def test_provider_from_string(value, expected):
    assert ModelProvider.from_string(value) is expected


def test_plain_claude_still_means_the_anthropic_api():
    """`claude` must keep resolving to the HTTP provider, not the CLI."""
    assert ModelProvider.from_string("claude") is ModelProvider.ANTHROPIC


def test_factory_builds_cli_models_and_maps_effort():
    claude = ModelFactory.create_model(
        ModelEndpoint(provider=ModelProvider.CLAUDE_CLI, model_name="sonnet", thinking_level="high")
    )
    assert isinstance(claude, ChatClaudeCLI)
    # thinking_level and reasoning_effort are one knob to a CLI.
    assert claude.reasoning_effort == "high"
    # The 60s HTTP default is not a usable process ceiling.
    assert claude.timeout_seconds >= 180

    codex = ModelFactory.create_model(
        ModelEndpoint(
            provider=ModelProvider.CODEX_CLI, model_name="gpt-5.5", reasoning_effort="low"
        )
    )
    assert isinstance(codex, ChatCodexCLI)
    assert codex.reasoning_effort == "low"


# ---------------------------------------------------------------------------
# Tool contract and envelope parsing
# ---------------------------------------------------------------------------


def test_normalize_tools_drops_provider_builtins():
    tools = normalize_tools([click_element, {"google_search": {}}])
    assert [t["name"] for t in tools] == ["click_element"]
    assert "index" in tools[0]["parameters"]["properties"]


def test_tool_contract_names_every_tool_and_its_schema():
    contract = build_tool_contract(normalize_tools([click_element]))
    assert "click_element" in contract
    assert '"args"' in contract
    assert "arguments" not in contract.split("Rules:")[1].split("\n")[1]


def test_tool_contract_switches_to_string_arguments_for_strict_backends():
    contract = build_tool_contract(normalize_tools([click_element]), args_as_string=True)
    assert '"arguments"' in contract
    assert "JSON *string*" in contract


def test_strict_response_schema_is_openai_strict_compatible():
    """Every object must forbid extra keys and require all its properties."""
    schema = response_json_schema(normalize_tools([click_element]))

    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, node
            assert set(node.get("required", [])) == set(node.get("properties", {})), node
        for value in node.values():
            if isinstance(value, dict):
                walk(value)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

    walk(schema)
    assert schema["properties"]["tool_calls"]["items"]["properties"]["name"]["enum"] == [
        "click_element"
    ]


def test_parse_envelope_extracts_tool_calls_and_thought():
    raw = json.dumps(
        {
            "thought": "tapping confirm",
            "text": "",
            "tool_calls": [{"name": "click_element", "args": {"index": 7, "reason": "confirm"}}],
        }
    )
    message = parse_envelope(raw, allowed_names=["click_element"])
    assert message.tool_calls[0]["name"] == "click_element"
    assert message.tool_calls[0]["args"] == {"index": 7, "reason": "confirm"}
    assert message.tool_calls[0]["id"]
    assert message.response_metadata["cli_thought"] == "tapping confirm"


def test_parse_envelope_accepts_string_arguments_and_fences():
    raw = (
        "Here you go:\n```json\n"
        + json.dumps(
            {
                "text": "",
                "tool_calls": [
                    {"name": "click_element", "arguments": '{"index": 3, "reason": "go"}'}
                ],
            }
        )
        + "\n```"
    )
    message = parse_envelope(raw, allowed_names=["click_element"])
    assert message.tool_calls[0]["args"] == {"index": 3, "reason": "go"}


def test_parse_envelope_drops_unbound_tools():
    raw = json.dumps({"text": "", "tool_calls": [{"name": "rm_rf", "args": {}}]})
    message = parse_envelope(raw, allowed_names=["click_element"])
    assert message.tool_calls == []


def test_parse_envelope_treats_prose_as_an_answer():
    """A model that answers in prose is answering, not failing."""
    message = parse_envelope("The screen shows the login form.", allowed_names=[])
    assert message.content == "The screen shows the login form."
    assert message.tool_calls == []


# ---------------------------------------------------------------------------
# History folding
# ---------------------------------------------------------------------------


def test_render_messages_folds_history_and_siphons_images():
    rendered = render_messages(
        [
            SystemMessage(content="You are the Operator."),
            HumanMessage(
                content=[
                    {"type": "text", "text": "Tap confirm."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG}"}},
                ]
            ),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "click_element", "args": {"index": 1}, "id": "1", "type": "tool_call"}
                ],
            ),
            ToolMessage(content="clicked", tool_call_id="1", name="click_element"),
        ],
        tool_contract="## Available tools",
    )
    assert "You are the Operator." in rendered.system
    assert "## Available tools" in rendered.system
    assert "Tap confirm." in rendered.turn
    assert "Result of click_element" in rendered.turn
    # The placeholder keeps the image's position in the transcript.
    assert "[image #1: image/png]" in rendered.turn
    assert len(rendered.images) == 1
    assert rendered.images[0].mime_type == "image/png"


@pytest.mark.parametrize(
    "block",
    [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG}"}},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _PNG}},
        {"type": "image", "data": _PNG, "mime_type": "image/png"},
        {"type": "media", "data": _PNG, "mime_type": "image/png"},
    ],
)
def test_every_image_block_dialect_is_understood(block):
    rendered = render_messages([HumanMessage(content=[block])])
    assert len(rendered.images) == 1


def test_older_images_are_dropped_with_a_breadcrumb():
    blocks = [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG}"}}
        for _ in range(5)
    ]
    rendered = render_messages([HumanMessage(content=blocks)], max_images=2)
    assert len(rendered.images) == 2
    assert "3 older image(s) were omitted" in rendered.turn


# ---------------------------------------------------------------------------
# Claude backend
# ---------------------------------------------------------------------------


def test_claude_argv_isolates_the_child_and_carries_images():
    model = ChatClaudeCLI(model_name="sonnet", reasoning_effort="high").bind_tools([click_element])
    prompt = model._prepare(
        [
            SystemMessage(content="sys"),
            HumanMessage(
                content=[
                    {"type": "text", "text": "hi"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG}"}},
                ]
            ),
        ]
    )
    argv, stdin_text = model.build_invocation(prompt, "/tmp/does-not-matter")

    # Isolation: no user config, no MCP servers (which would let the child call
    # back into the ARTEMIS task that spawned it), no built-in tools.
    assert "--safe-mode" in argv
    assert "--strict-mcp-config" in argv
    assert "--disable-slash-commands" in argv
    assert argv[argv.index("--tools") + 1] == ""
    # A full system-prompt override, not an append: that is what drops the
    # default preamble from ~4.7k tokens to ~550.
    assert "--system-prompt" in argv
    assert "--append-system-prompt" not in argv
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--effort") + 1] == "high"

    payload = json.loads(stdin_text)
    assert payload["type"] == "user"
    image_blocks = [b for b in payload["message"]["content"] if b["type"] == "image"]
    assert image_blocks[0]["source"]["media_type"] == "image/png"


def test_claude_grounding_enables_web_search():
    model = ChatClaudeCLI(enable_grounding=True)
    argv, _ = model.build_invocation(model._prepare([HumanMessage(content="hi")]), "/tmp")
    assert argv[argv.index("--tools") + 1] == "WebSearch"


def _claude_stream(result: str, **overrides) -> str:
    event = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": result,
        "usage": {
            "input_tokens": 10,
            "cache_creation_input_tokens": 5,
            "cache_read_input_tokens": 100,
            "output_tokens": 7,
        },
    }
    event.update(overrides)
    return json.dumps({"type": "system", "subtype": "init"}) + "\n" + json.dumps(event) + "\n"


def test_claude_parse_output_reports_usage_including_cache():
    model = ChatClaudeCLI()
    text, usage = model.parse_output(_claude_stream('{"text": "ok"}'), "", "/tmp")
    assert text == '{"text": "ok"}'
    # Cache creation and cache reads are billed as input.
    assert usage == {"input_tokens": 115, "output_tokens": 7, "cached_tokens": 100}


def test_claude_usage_reaches_langchain_usage_metadata():
    """The token meter reads usage_metadata, so the counts must land there."""
    model = ChatClaudeCLI()
    message = model._finalize(*model.parse_output(_claude_stream('{"text": "ok"}'), "", "/tmp"))
    assert message.usage_metadata["input_tokens"] == 115
    assert message.usage_metadata["total_tokens"] == 122
    assert message.usage_metadata["input_token_details"]["cache_read"] == 100


def test_claude_spent_subscription_window_is_a_rate_limit():
    """A spent window must retry and fail over like an HTTP 429, not die."""
    model = ChatClaudeCLI()
    stream = (
        json.dumps(
            {
                "type": "rate_limit_event",
                "rate_limit_info": {"status": "rejected", "resetsAt": 1789021200},
            }
        )
        + "\n"
    )
    with pytest.raises(CLIInvocationError) as excinfo:
        model.parse_output(stream, "", "/tmp")
    assert classify_failure(excinfo.value).category is FailureCategory.RATE_LIMIT


def test_claude_missing_result_event_is_an_error():
    with pytest.raises(CLIInvocationError):
        ChatClaudeCLI().parse_output("", "boom", "/tmp")


# ---------------------------------------------------------------------------
# Codex backend
# ---------------------------------------------------------------------------


def test_codex_writes_images_and_a_strict_schema(tmp_path):
    model = ChatCodexCLI(model_name="gpt-5.5", reasoning_effort="low").bind_tools([click_element])
    prompt = model._prepare(
        [
            SystemMessage(content="sys"),
            HumanMessage(
                content=[
                    {"type": "text", "text": "hi"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_PNG}"}},
                ]
            ),
        ]
    )
    argv, stdin_text = model.build_invocation(prompt, str(tmp_path))

    assert argv[:2] == ["codex", "exec"]
    assert "--ephemeral" in argv
    assert "--ignore-user-config" in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("--config") + 1] == "model_reasoning_effort=low"

    schema = json.loads((tmp_path / "schema.json").read_text())
    # Strict mode cannot express a free-form argument object.
    assert schema["properties"]["tool_calls"]["items"]["properties"]["arguments"] == {
        "type": "string"
    }

    image_path = argv[argv.index("--image") + 1]
    assert (tmp_path / "image-1.png").exists()
    assert image_path.endswith("image-1.png")

    # `--image` is variadic, so the prompt must travel on stdin or it would be
    # swallowed as another image path.
    assert "hi" in stdin_text
    assert stdin_text not in argv


def test_codex_parse_output_prefers_the_final_message_file(tmp_path):
    (tmp_path / "final.txt").write_text('{"text": "from file"}')
    stream = (
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": '{"text": "from stream"}'},
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 27835,
                    "cached_input_tokens": 2432,
                    "output_tokens": 62,
                    "reasoning_output_tokens": 8,
                },
            }
        )
        + "\n"
    )
    text, usage = ChatCodexCLI().parse_output(stream, "", str(tmp_path))
    assert text == '{"text": "from file"}'
    assert usage == {"input_tokens": 27835, "output_tokens": 70, "cached_tokens": 2432}


def test_codex_falls_back_to_the_event_stream(tmp_path):
    stream = (
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": '{"text": "streamed"}'},
            }
        )
        + "\n"
    )
    text, _ = ChatCodexCLI().parse_output(stream, "", str(tmp_path))
    assert text == '{"text": "streamed"}'


def test_codex_stale_cli_error_is_not_retried(tmp_path):
    """ "Requires a newer version" is a local defect; retrying cannot fix it."""
    stream = (
        json.dumps(
            {
                "type": "error",
                "status": 400,
                "error": {"message": "The model requires a newer version of Codex."},
            }
        )
        + "\n"
    )
    with pytest.raises(CLIInvocationError) as excinfo:
        ChatCodexCLI().parse_output(stream, "", str(tmp_path))
    failure = classify_failure(excinfo.value)
    assert failure.category is FailureCategory.BAD_REQUEST
    assert failure.retryable is False


# ---------------------------------------------------------------------------
# Environment isolation
# ---------------------------------------------------------------------------


def test_provider_api_keys_are_kept_out_of_the_child(monkeypatch):
    """An inherited key would silently switch a CLI to metered API billing."""
    from artemis.llm.cli.base import child_env

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("GOOGLE_API_KEY", "goog-should-not-leak")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.delenv("ARTEMIS_CLI_INHERIT_API_KEYS", raising=False)

    env = child_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert "GOOGLE_API_KEY" not in env
    assert env["PATH"] == "/usr/bin"


def test_api_keys_can_be_inherited_on_purpose(monkeypatch):
    from artemis.llm.cli.base import child_env

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-deliberate")
    monkeypatch.setenv("ARTEMIS_CLI_INHERIT_API_KEYS", "1")
    assert child_env()["ANTHROPIC_API_KEY"] == "sk-deliberate"


def test_a_missing_binary_fails_fast_without_retrying(monkeypatch):
    monkeypatch.setattr("artemis.llm.cli.base.shutil.which", lambda _: None)
    with pytest.raises(CLIInvocationError) as excinfo:
        ChatClaudeCLI().invoke([HumanMessage(content="hi")])
    assert classify_failure(excinfo.value).retryable is False


def test_structured_contract_names_the_schema_fields():
    """A CLI asked for structured output must be told the field names.

    Regression: the contract promised only "reply with a single JSON value",
    never the schema, so the model invented plausible-looking keys. A run's
    planner_validation asked for ValidationResult{is_approved, feedback} and
    got {'approval': 'approved', ...} every single time - semantically right,
    structurally unusable, and the node never produced a verdict. Codex is
    unaffected because it enforces the shape through --output-schema.
    """
    from pydantic import BaseModel, Field

    class ValidationResult(BaseModel):
        is_approved: bool = Field(description="True if the plan still serves the goal.")
        feedback: str = Field(description="One or two sentences naming the concern.")

    model = ChatClaudeCLI(model_name="sonnet").with_structured_output(ValidationResult)
    # with_structured_output returns model | parser; the model is the first step.
    cli_model = model.steps[0] if hasattr(model, "steps") else model.first
    prompt = cli_model._prepare([HumanMessage(content="review this plan")])

    rendered = json.dumps(prompt, default=str)
    assert "is_approved" in rendered, "the contract must name the required fields"
    assert "feedback" in rendered
