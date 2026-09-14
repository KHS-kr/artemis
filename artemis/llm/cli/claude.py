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

"""Claude Code CLI (``claude -p``) as an ARTEMIS chat model.

The CLI is driven as a stateless one-shot text/vision model, not as a coding
agent.  Three flags do the work:

``--safe-mode``
    Disables every customization - ``CLAUDE.md``, skills, plugins, hooks, MCP
    servers, custom agents - while leaving auth, model selection and
    permissions working normally.  This is what keeps subscription (OAuth)
    login intact; ``--bare`` looks similar but forces ``ANTHROPIC_API_KEY``
    and never reads OAuth, which would defeat the point.  It also breaks the
    recursion hazard: ``artemis mcp --install claude`` writes rules telling
    Claude Code to drive devices through the ARTEMIS MCP server, and a child
    process that loaded them could call back into the task that spawned it.

``--tools ""``
    Removes the built-in tool set, so the child cannot read files or run
    commands and answers directly instead of looping.

``--input-format stream-json``
    The only way to hand the CLI inline images: base64 blocks in a user
    message.  With ``--tools ""`` there is no ``Read`` tool, so file paths
    would be useless.

Measured on claude 2.1.266: a full override via ``--system-prompt`` drops
per-call overhead from ~4.7k tokens of default system prompt to ~550, and a
call costs roughly 1.6s wall clock.
"""

from __future__ import annotations

import json
from typing import Any

from artemis.llm.cli.base import CLIChatModel, CLIInvocationError, RenderedPrompt
from artemis.utils.logger import get_logger

logger = get_logger(__name__)

#: ``--effort`` accepts these; ARTEMIS thinking levels are mapped onto them.
_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
_EFFORT_ALIASES = {"none": "low", "minimal": "low"}

#: Warn once the subscription window is nearly spent - a Pro-profile run makes
#: hundreds of calls and will otherwise hit the wall mid-task.
_RATE_LIMIT_WARN_UTILIZATION = 0.9


class ChatClaudeCLI(CLIChatModel):
    """Chat model backed by the local ``claude`` binary and its subscription."""

    binary: str = "claude"
    model_name: str = "sonnet"

    def _effort(self) -> str | None:
        raw = (self.reasoning_effort or "").strip().lower()
        if not raw:
            return None
        mapped = _EFFORT_ALIASES.get(raw, raw)
        if mapped not in _EFFORT_LEVELS:
            logger.debug(f"Ignoring unsupported claude --effort value {raw!r}")
            return None
        return mapped

    def build_invocation(self, prompt: RenderedPrompt, workdir: str) -> tuple[list[str], str]:
        argv = [
            self.binary,
            "--print",
            "--safe-mode",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--tools",
            "WebSearch" if self.enable_grounding else "",
            "--system-prompt",
            prompt.system or "You are a helpful assistant.",
        ]
        if self.model_name:
            argv += ["--model", self.model_name]
        effort = self._effort()
        if effort:
            argv += ["--effort", effort]

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt.turn}]
        for blob in prompt.images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": blob.mime_type,
                        "data": blob.base64,
                    },
                }
            )
        stdin_text = (
            json.dumps(
                {"type": "user", "message": {"role": "user", "content": content}},
                ensure_ascii=False,
            )
            + "\n"
        )
        return argv, stdin_text

    def parse_output(self, stdout: str, stderr: str, workdir: str) -> tuple[str, dict[str, int]]:
        result_event: dict[str, Any] | None = None
        for line in stdout.splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_type = event.get("type")
            if event_type == "rate_limit_event":
                self._check_rate_limit(event.get("rate_limit_info") or {})
            elif event_type == "result":
                result_event = event

        if result_event is None:
            detail = (stderr.strip() or stdout.strip())[-800:]
            raise CLIInvocationError(
                f"claude produced no result event. Output: {detail or '(empty)'}"
            )
        if result_event.get("is_error"):
            subtype = result_event.get("subtype") or "error"
            detail = str(result_event.get("result") or subtype)
            raise CLIInvocationError(f"claude reported {subtype}: {detail}")

        text = result_event.get("result")
        if not isinstance(text, str):
            raise CLIInvocationError(
                f"claude result carried no text (subtype={result_event.get('subtype')!r})"
            )
        return text, _usage_from_result(result_event.get("usage") or {})

    def _check_rate_limit(self, info: dict[str, Any]) -> None:
        status = str(info.get("status") or "").lower()
        if status and status != "allowed":
            resets_at = info.get("resetsAt")
            raise CLIInvocationError(
                f"claude subscription rate limit reached (status={status}, "
                f"resets_at={resets_at}). Switch the node to an API-key provider "
                f"or wait for the window to reset.",
                status_code=429,
            )
        windows = info.get("unifiedWindows") or {}
        for name, window in windows.items():
            try:
                utilization = float(window.get("utilization", 0.0))
            except (TypeError, ValueError):
                continue
            if utilization >= _RATE_LIMIT_WARN_UTILIZATION:
                logger.warning(
                    f"Claude subscription {name} window is {utilization:.0%} spent "
                    f"(resets at {window.get('resetsAt')})."
                )


def _usage_from_result(usage: dict[str, Any]) -> dict[str, int]:
    """Fold the CLI's usage block into the counts the token meter records.

    Cache creation is billed as input, so both cache fields join the input
    total while the cache-read part is also reported separately.
    """

    def _int(key: str) -> int:
        try:
            return int(usage.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    cache_read = _int("cache_read_input_tokens")
    return {
        "input_tokens": _int("input_tokens") + _int("cache_creation_input_tokens") + cache_read,
        "output_tokens": _int("output_tokens"),
        "cached_tokens": cache_read,
    }
