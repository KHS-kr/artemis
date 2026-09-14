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

"""Coding-agent CLIs (``claude``, ``codex``) exposed as ARTEMIS chat models.

These backends spend a local CLI subscription instead of a provider API key,
so ARTEMIS can run without ``GOOGLE_API_KEY``/``ANTHROPIC_API_KEY``.  They
are ordinary ``BaseChatModel`` implementations, which is what lets the
fallback chains, token meter, tracing and LangGraph nodes above them stay
unchanged.
"""

from artemis.llm.cli.base import (
    CLI_BINARIES,
    CLIChatModel,
    CLIInvocationError,
    ImageBlob,
    RenderedPrompt,
    check_cli_backend,
    cli_binary_for,
    render_messages,
)
from artemis.llm.cli.claude import ChatClaudeCLI
from artemis.llm.cli.codex import ChatCodexCLI
from artemis.llm.cli.envelope import (
    build_tool_contract,
    normalize_tools,
    parse_envelope,
    response_json_schema,
    tool_names,
)

__all__ = [
    "CLI_BINARIES",
    "CLIChatModel",
    "CLIInvocationError",
    "ChatClaudeCLI",
    "ChatCodexCLI",
    "ImageBlob",
    "RenderedPrompt",
    "build_tool_contract",
    "check_cli_backend",
    "cli_binary_for",
    "normalize_tools",
    "parse_envelope",
    "render_messages",
    "response_json_schema",
    "tool_names",
]
