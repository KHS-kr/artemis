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

"""Codex CLI (``codex exec``) as an ARTEMIS chat model.

Codex is the mirror image of the Claude backend: weaker isolation, stronger
output guarantees.

* ``--output-schema`` hard-enforces the reply shape, so tool calls come back
  structurally valid instead of parsed out of prose.  It is OpenAI strict
  mode, which is why arguments travel as a JSON-encoded string - see
  :func:`~artemis.llm.cli.envelope.response_json_schema`.
* ``-i/--image`` attaches screenshots as files, so images are written to the
  call's temp directory rather than inlined.
* There is no ``--system-prompt`` and no equivalent of Claude's
  ``--safe-mode``: instructions go in the prompt body, and every call ships
  Codex's own coding-agent instructions.  Measured on codex-cli 0.137.0 that
  is ~27k input tokens and ~13s per call, against ~550 tokens and ~1.6s for
  the Claude backend - so prefer Codex for nodes where its judgment earns
  that cost, not as a default for high-frequency judges.

Two flags are load-bearing for correctness rather than cost.  ``--image`` is
variadic, so the prompt must arrive on stdin: passed positionally after
``-i`` it is swallowed as another image path, and Codex then blocks waiting
for stdin that never closes.  And ``codex exec`` reads its prompt from stdin
whenever no positional prompt survives, which is exactly what this backend
relies on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from artemis.llm.cli.base import CLIChatModel, CLIInvocationError, RenderedPrompt
from artemis.llm.cli.envelope import response_json_schema
from artemis.utils.logger import get_logger

logger = get_logger(__name__)

#: ``model_reasoning_effort`` variants accepted by the Responses backend.
_EFFORT_LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh")
_EFFORT_ALIASES = {"minimal": "minimal", "none": "none"}


class ChatCodexCLI(CLIChatModel):
    """Chat model backed by the local ``codex`` binary and its subscription."""

    binary: str = "codex"
    model_name: str = ""
    args_as_string: bool = True
    #: ``codex exec`` still owns a shell inside its sandbox; ``read-only``
    #: keeps a stray command from touching the host running the device tests.
    sandbox_mode: str = "read-only"

    def _clone_fields(self) -> dict[str, Any]:
        return {**super()._clone_fields(), "sandbox_mode": self.sandbox_mode}

    def _effort(self) -> str | None:
        raw = (self.reasoning_effort or "").strip().lower()
        if not raw:
            return None
        mapped = _EFFORT_ALIASES.get(raw, raw)
        if mapped not in _EFFORT_LEVELS:
            logger.debug(f"Ignoring unsupported codex reasoning effort {raw!r}")
            return None
        return mapped

    def build_invocation(self, prompt: RenderedPrompt, workdir: str) -> tuple[list[str], str]:
        work = Path(workdir)
        final_path = work / "final.txt"
        argv = [
            self.binary,
            "exec",
            "--ephemeral",
            "--skip-git-repo-check",
            "--ignore-rules",
            "--ignore-user-config",
            "--sandbox",
            self.sandbox_mode,
            "--json",
            "--color",
            "never",
            "--output-last-message",
            str(final_path),
        ]
        if self.model_name:
            argv += ["--model", self.model_name]
        effort = self._effort()
        if effort:
            argv += ["--config", f"model_reasoning_effort={effort}"]

        schema_path = work / "schema.json"
        schema_path.write_text(json.dumps(response_json_schema(self.bound_tools)), encoding="utf-8")
        argv += ["--output-schema", str(schema_path)]

        for index, blob in enumerate(prompt.images, start=1):
            image_path = work / f"image-{index}.{blob.extension}"
            image_path.write_bytes(blob.data)
            argv += ["--image", str(image_path)]

        header = (
            "You are being used as a stateless reasoning endpoint, not as a coding "
            "agent. Do not read files, run commands, or modify the workspace: answer "
            "directly from the conversation below."
        )
        sections = [header]
        if prompt.system:
            sections.append(f"# Instructions\n\n{prompt.system}")
        sections.append(f"# Conversation\n\n{prompt.turn}")
        if prompt.images:
            sections.append(
                f"{len(prompt.images)} image(s) are attached, in the order the "
                "`[image #N: ...]` markers appear above."
            )
        return argv, "\n\n".join(sections) + "\n"

    def parse_output(self, stdout: str, stderr: str, workdir: str) -> tuple[str, dict[str, int]]:
        usage: dict[str, int] = {}
        message: str | None = None
        error: dict[str, Any] | None = None

        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_type = event.get("type")
            if event_type == "turn.completed":
                usage = _usage_from_turn(event.get("usage") or {})
            elif event_type == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                    message = item["text"]
            elif event_type == "error":
                error = event

        # ``--output-last-message`` is the authoritative final text; the event
        # stream is the fallback when the file was never written.
        final_path = Path(workdir) / "final.txt"
        if final_path.exists():
            file_text = final_path.read_text(encoding="utf-8", errors="replace").strip()
            if file_text:
                message = file_text

        if message is None:
            detail = _error_detail(error) or (stderr.strip() or stdout.strip())[-800:]
            raise CLIInvocationError(
                f"codex produced no agent message. {detail or '(no output)'}",
                status_code=_error_status(error),
            )
        return message, usage


def _error_detail(error: dict[str, Any] | None) -> str:
    if not error:
        return ""
    inner = error.get("error")
    if isinstance(inner, dict):
        return str(inner.get("message") or inner)
    return str(error.get("message") or error)


def _error_status(error: dict[str, Any] | None) -> int | None:
    if not error:
        return None
    status = error.get("status")
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def _usage_from_turn(usage: dict[str, Any]) -> dict[str, int]:
    """Map a ``turn.completed`` usage block onto the meter's counts.

    Codex reports ``cached_input_tokens`` as a subset of ``input_tokens``, and
    reasoning output separately from visible output.
    """

    def _int(key: str) -> int:
        try:
            return int(usage.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    return {
        "input_tokens": _int("input_tokens"),
        "output_tokens": _int("output_tokens") + _int("reasoning_output_tokens"),
        "cached_tokens": _int("cached_input_tokens"),
    }
