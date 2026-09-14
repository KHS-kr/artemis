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

"""Shared plumbing for coding-agent CLI chat models.

``claude -p`` and ``codex exec`` are subscription-authenticated local
processes rather than HTTP endpoints, but ARTEMIS only ever talks to a
``BaseChatModel``.  This module holds everything the two share:

* **History folding.** Every invocation is one process, so the whole ARTEMIS
  conversation is folded into a single rendered turn.  That matches how the
  graph already works - nodes re-send full history each step and compress it
  themselves - and avoids depending on a CLI's session replay semantics.
* **Image extraction.** Screenshots arrive as LangChain content blocks in
  four different shapes; they are normalized to raw bytes here and handed to
  each backend in whatever form it accepts.
* **Environment isolation.** Provider API keys are stripped from the child
  environment so the CLI authenticates with the user's subscription (OAuth)
  instead of silently billing an API key that happens to sit in ``.env``.
* **Failure shaping.** Process failures are raised as
  :class:`CLIInvocationError` with a ``status_code``, so
  ``artemis.llm.reliability.classify_failure`` routes them through the same
  retry, fallback and circuit-breaker policy as HTTP providers.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
import os
import shutil
import subprocess
from typing import Any

from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, Field

from artemis.llm.cli.envelope import (
    build_tool_contract,
    normalize_tools,
    parse_envelope,
    tool_names,
)
from artemis.llm.structured import StructuredOutputError, parse_structured, ParseFailure
from artemis.utils.logger import get_logger

logger = get_logger(__name__)

#: Provider credentials are removed from the child environment: a CLI backend
#: is chosen precisely to spend a subscription, and an inherited API key would
#: silently switch it back to metered API billing.  Set
#: ARTEMIS_CLI_INHERIT_API_KEYS=1 to keep them (useful when a CLI is
#: deliberately pointed at an API key or a third-party gateway).
_STRIPPED_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GCP_API_KEY",
    "OPEN_ROUTER_API_KEY",
    "XAI_API_KEY",
)

#: Screenshots dominate the payload. ARTEMIS already folds older steps into
#: visual summaries, so only the newest frames are still raw images; keep the
#: most recent ones and leave a breadcrumb for the rest.
DEFAULT_MAX_IMAGES = 8


#: Provider name -> binary that serves it.
CLI_BINARIES: dict[str, str] = {"claude_cli": "claude", "codex_cli": "codex"}

#: How each CLI is signed in, for actionable error messages.
_CLI_LOGIN_HINTS: dict[str, str] = {
    "claude": "run `claude` once and sign in (or `claude /login`)",
    "codex": "run `codex login`",
}


def cli_binary_for(provider: Any) -> str | None:
    """The binary backing a provider name, or None when it is not a CLI provider."""
    name = str(getattr(provider, "value", provider) or "").lower()
    name = name.replace("-", "_")
    return CLI_BINARIES.get(name)


def check_cli_backend(provider: Any) -> tuple[bool, str]:
    """Whether a CLI provider can run here, plus a human-readable reason.

    Only presence on PATH is checked: verifying the login would mean spending
    a real model call on every config validation. A signed-out binary instead
    surfaces at call time as an authentication failure, which the reliability
    layer already routes to the fallback endpoint.
    """
    binary = cli_binary_for(provider)
    if binary is None:
        return False, f"{provider!r} is not a CLI-backed provider"
    path = shutil.which(binary)
    if path is None:
        hint = _CLI_LOGIN_HINTS.get(binary, "install the CLI and sign in")
        return False, f"{binary!r} was not found on PATH - install it, then {hint}"
    return True, f"{binary} found at {path}"


class CLIInvocationError(Exception):
    """A CLI backend call that failed, shaped for ``classify_failure``.

    ``status_code`` is what makes the existing reliability layer treat these
    like provider errors: 429 for a spent subscription window, 401 for a
    logged-out CLI, 504 for a process timeout, 400 for a malformed request.
    """

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ImageBlob:
    """One decoded inline image."""

    mime_type: str
    data: bytes

    @property
    def base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")

    @property
    def extension(self) -> str:
        subtype = self.mime_type.rsplit("/", 1)[-1].lower()
        return {"jpeg": "jpg", "svg+xml": "svg"}.get(subtype, subtype or "png")


@dataclass
class RenderedPrompt:
    """A whole conversation folded into what a one-shot CLI call needs."""

    system: str
    turn: str
    images: list[ImageBlob]


def _decode_data_url(url: str) -> ImageBlob | None:
    if not url.startswith("data:"):
        return None
    header, _, payload = url.partition(",")
    if not payload:
        return None
    mime_type = header[5:].split(";", 1)[0] or "image/png"
    try:
        return ImageBlob(mime_type=mime_type, data=base64.b64decode(payload, validate=False))
    except ValueError:
        # binascii.Error subclasses ValueError: a truncated or non-base64 payload.
        return None


def _extract_image(block: dict) -> ImageBlob | None:
    """Pull an inline image out of any content-block dialect ARTEMIS emits."""
    block_type = block.get("type")

    if block_type == "image_url":
        url = block.get("image_url")
        if isinstance(url, dict):
            url = url.get("url")
        return _decode_data_url(url) if isinstance(url, str) else None

    if block_type == "image":
        source = block.get("source")
        if isinstance(source, dict):
            data = source.get("data")
            if isinstance(data, str):
                return ImageBlob(
                    mime_type=source.get("media_type") or "image/png",
                    data=base64.b64decode(data, validate=False),
                )
            url = source.get("url")
            if isinstance(url, str):
                return _decode_data_url(url)
        # LangChain v1 standard block: {"type":"image","data":...,"mime_type":...}
        data = block.get("data")
        if isinstance(data, str):
            return ImageBlob(
                mime_type=block.get("mime_type") or "image/png",
                data=base64.b64decode(data, validate=False),
            )
        return None

    if block_type in ("media", "inline_data"):
        data = block.get("data")
        mime_type = block.get("mime_type") or block.get("mimeType") or "image/png"
        if isinstance(data, bytes):
            return ImageBlob(mime_type=mime_type, data=data)
        if isinstance(data, str):
            try:
                return ImageBlob(mime_type=mime_type, data=base64.b64decode(data, validate=False))
            except ValueError:
                return None
    return None


def _render_content(content: Any, images: list[ImageBlob]) -> str:
    """Flatten one message's content to text, siphoning images off to ``images``."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        blob = _extract_image(item)
        if blob is not None:
            images.append(blob)
            parts.append(f"[image #{len(images)}: {blob.mime_type}]")
            continue
        item_type = item.get("type")
        if item_type == "thinking":
            continue
        text = item.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(p for p in parts if p)


def _render_tool_calls(message: AIMessage) -> str:
    calls = getattr(message, "tool_calls", None) or []
    if not calls:
        return ""
    import json

    payload = [{"name": c.get("name"), "args": c.get("args") or {}} for c in calls]
    return json.dumps({"tool_calls": payload}, ensure_ascii=False)


def render_messages(
    messages: Sequence[BaseMessage],
    *,
    tool_contract: str = "",
    max_images: int = DEFAULT_MAX_IMAGES,
) -> RenderedPrompt:
    """Fold a LangChain conversation into one system prompt plus one turn."""
    system_parts: list[str] = []
    turn_parts: list[str] = []
    images: list[ImageBlob] = []

    for message in messages:
        if isinstance(message, SystemMessage):
            system_parts.append(_render_content(message.content, images))
            continue
        if isinstance(message, HumanMessage):
            body = _render_content(message.content, images)
            if body:
                turn_parts.append(f"## User\n{body}")
            continue
        if isinstance(message, AIMessage):
            body = _render_content(message.content, images)
            calls = _render_tool_calls(message)
            chunk = "\n".join(p for p in (body, calls) if p)
            if chunk:
                turn_parts.append(f"## Assistant (previous turn)\n{chunk}")
            continue
        if isinstance(message, ToolMessage):
            name = getattr(message, "name", None) or "tool"
            body = _render_content(message.content, images)
            turn_parts.append(f"## Result of {name}\n{body}")
            continue
        body = _render_content(getattr(message, "content", None), images)
        if body:
            turn_parts.append(body)

    # System messages may themselves have carried images; those stay in order
    # with the rest, since a backend receives one flat image list either way.
    dropped = 0
    if len(images) > max_images:
        dropped = len(images) - max_images
        images = images[-max_images:]

    system = "\n\n".join(p for p in system_parts if p)
    if tool_contract:
        system = f"{system}\n\n{tool_contract}" if system else tool_contract

    turn = "\n\n".join(turn_parts) or "(no conversation content)"
    if dropped:
        turn = (
            f"[note: {dropped} older image(s) were omitted to bound payload size; "
            f"the {len(images)} most recent image(s) are attached]\n\n" + turn
        )
    return RenderedPrompt(system=system, turn=turn, images=images)


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The child process environment: inherited, minus provider credentials."""
    env = dict(os.environ)
    if os.environ.get("ARTEMIS_CLI_INHERIT_API_KEYS") != "1":
        for key in _STRIPPED_ENV_KEYS:
            env.pop(key, None)
    env.update(extra or {})
    return env


class CLIChatModel(BaseChatModel):
    """Base class for chat models backed by a local coding-agent CLI.

    Subclasses implement :meth:`build_invocation` (argv, stdin and any
    temporary files) and :meth:`parse_output` (stdout to text plus usage).
    """

    model_name: str = ""
    binary: str = ""
    timeout_seconds: float = 300.0
    reasoning_effort: str | None = None
    enable_grounding: bool = False
    max_images: int = DEFAULT_MAX_IMAGES
    bound_tools: list[dict] = Field(default_factory=list)
    #: Set by :meth:`with_structured_output`; parsed out of the reply text.
    structured_schema: Any = None
    #: True when the backend hard-enforces an OpenAI strict schema, which
    #: cannot express a free-form argument object (see
    #: :func:`~artemis.llm.cli.envelope.response_json_schema`).
    args_as_string: bool = False

    model_config = {"arbitrary_types_allowed": True}

    # -- subclass contract ------------------------------------------------

    def build_invocation(self, prompt: RenderedPrompt, workdir: str) -> tuple[list[str], str]:
        """Return ``(argv, stdin_text)`` for one call, using ``workdir`` for temp files."""
        raise NotImplementedError

    def parse_output(self, stdout: str, stderr: str, workdir: str) -> tuple[str, dict[str, int]]:
        """Return ``(final_text, usage)`` from a completed process."""
        raise NotImplementedError

    def extra_response_metadata(self) -> dict[str, Any]:
        return {}

    # -- LangChain surface ------------------------------------------------

    @property
    def _llm_type(self) -> str:
        return f"artemis-{self.binary}-cli"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"binary": self.binary, "model": self.model_name}

    def _clone_fields(self) -> dict[str, Any]:
        """The constructor payload that :meth:`_clone` carries over.

        Subclasses extend this instead of overriding ``_clone``, so their own
        fields survive ``bind_tools`` without narrowing the return type.
        """
        return {
            "model_name": self.model_name,
            "binary": self.binary,
            "timeout_seconds": self.timeout_seconds,
            "reasoning_effort": self.reasoning_effort,
            "enable_grounding": self.enable_grounding,
            "max_images": self.max_images,
            "bound_tools": list(self.bound_tools),
            "structured_schema": self.structured_schema,
            "args_as_string": self.args_as_string,
        }

    def _clone(self, **overrides: Any) -> CLIChatModel:
        data = self._clone_fields()
        data.update(overrides)
        return type(self)(**data)

    def bind_tools(self, tools: Any, *args: Any, **kwargs: Any) -> CLIChatModel:
        """Record tools as a prompt contract - the CLI has no native tool API.

        Extra arguments are accepted and dropped on purpose: callers reach
        this through ``RobustChatModelWrapper``, which forwards provider
        specifics such as ``tool_config`` that only Gemini understands.
        """
        if args or kwargs:
            logger.debug(
                f"CLI backend ignores unsupported bind_tools arguments: "
                f"{list(args)} {sorted(kwargs)}"
            )
        return self._clone(bound_tools=normalize_tools(tools))

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable:
        """Ask for JSON and validate it, since no native schema mode exists."""
        if kwargs:
            logger.debug(
                f"CLI backend ignores unsupported with_structured_output kwargs: {sorted(kwargs)}"
            )
        model = self._clone(structured_schema=schema)

        def _parse(message: Any) -> Any:
            target = schema if isinstance(schema, type) and issubclass(schema, BaseModel) else None
            parsed = parse_structured(getattr(message, "content", message), target)
            if isinstance(parsed, ParseFailure):
                raise StructuredOutputError(parsed)
            return parsed

        return model | RunnableLambda(_parse)

    # -- execution --------------------------------------------------------

    def _prepare(self, messages: Sequence[BaseMessage]) -> RenderedPrompt:
        if self.structured_schema is not None and not self.bound_tools:
            # with_structured_output parses the reply itself, so all it needs is
            # a promise of bare JSON.
            contract = (
                "## Response format\n"
                "Reply with a single JSON value and nothing else - no prose outside "
                "it, no markdown fences."
            )
        else:
            contract = build_tool_contract(self.bound_tools, args_as_string=self.args_as_string)
        return render_messages(messages, tool_contract=contract, max_images=self.max_images)

    def _finalize(self, text: str, usage: dict[str, int]) -> AIMessage:
        return parse_envelope(
            text,
            allowed_names=tool_names(self.bound_tools),
            usage=_usage_metadata(usage),
            response_metadata={
                "model_name": self.model_name,
                "provider": self._llm_type,
                **self.extra_response_metadata(),
            },
        )

    def _run_sync(self, messages: Sequence[BaseMessage]) -> AIMessage:
        import tempfile

        prompt = self._prepare(messages)
        with tempfile.TemporaryDirectory(prefix="artemis-cli-") as workdir:
            argv, stdin_text = self.build_invocation(prompt, workdir)
            self._require_binary()
            try:
                completed = subprocess.run(
                    argv,
                    input=stdin_text,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    cwd=workdir,
                    env=child_env(),
                    check=False,
                )
            except subprocess.TimeoutExpired as e:
                raise CLIInvocationError(
                    f"{self.binary} timed out after {self.timeout_seconds:.0f}s", status_code=504
                ) from e
            self._check_exit(completed.returncode, completed.stdout or "", completed.stderr or "")
            text, usage = self.parse_output(completed.stdout or "", completed.stderr or "", workdir)
        return self._finalize(text, usage)

    async def _run_async(self, messages: Sequence[BaseMessage]) -> AIMessage:
        import tempfile

        prompt = self._prepare(messages)
        with tempfile.TemporaryDirectory(prefix="artemis-cli-") as workdir:
            argv, stdin_text = self.build_invocation(prompt, workdir)
            self._require_binary()
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                env=child_env(),
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(stdin_text.encode("utf-8")),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError as e:
                _terminate(process)
                raise CLIInvocationError(
                    f"{self.binary} timed out after {self.timeout_seconds:.0f}s", status_code=504
                ) from e
            except asyncio.CancelledError:
                _terminate(process)
                raise
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            self._check_exit(process.returncode or 0, stdout, stderr)
            text, usage = self.parse_output(stdout, stderr, workdir)
        return self._finalize(text, usage)

    def _require_binary(self) -> None:
        if shutil.which(self.binary) is None:
            raise CLIInvocationError(
                f"{self.binary!r} is not on PATH. Install the CLI and sign in, "
                f"or point the node at an API-key provider instead.",
                status_code=400,
            )

    def _check_exit(self, returncode: int, stdout: str, stderr: str) -> None:
        if returncode == 0:
            return
        detail = (stderr.strip() or stdout.strip())[-1200:]
        lowered = detail.lower()
        status = None
        if "rate limit" in lowered or "usage limit" in lowered or "quota" in lowered:
            status = 429
        elif "not logged in" in lowered or "log in" in lowered or "unauthorized" in lowered:
            status = 401
        elif "requires a newer version" in lowered or "please upgrade" in lowered:
            # A stale CLI is a local defect: retrying and falling back to the
            # same binary cannot fix it, so surface it as a bad request.
            status = 400
        raise CLIInvocationError(
            f"{self.binary} exited with code {returncode}: {detail}", status_code=status
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._run_sync(messages))])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=await self._run_async(messages))])

    # A CLI hands back one final message. Streaming its raw text would leak the
    # JSON envelope into the live UI, so one complete chunk is emitted instead.
    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        yield _as_chunk(self._run_sync(messages))

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        yield _as_chunk(await self._run_async(messages))


def _terminate(process: Any) -> None:
    try:
        process.kill()
    except ProcessLookupError:
        pass
    except (OSError, AttributeError) as e:  # pragma: no cover - defensive
        logger.debug(f"Could not kill CLI subprocess: {e}")


def _as_chunk(message: AIMessage) -> ChatGenerationChunk:
    import json

    tool_call_chunks = [
        {
            "name": call["name"],
            "args": json.dumps(call.get("args") or {}, ensure_ascii=False),
            "id": call.get("id"),
            "index": index,
            "type": "tool_call_chunk",
        }
        for index, call in enumerate(message.tool_calls or [])
    ]
    return ChatGenerationChunk(
        message=AIMessageChunk(
            content=message.content,
            tool_call_chunks=tool_call_chunks,
            usage_metadata=message.usage_metadata,
            response_metadata=message.response_metadata,
        )
    )


def _usage_metadata(usage: dict[str, int] | None) -> dict[str, Any] | None:
    """Shape raw counts as LangChain ``usage_metadata`` for the token meter."""
    if not usage:
        return None
    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    cached = int(usage.get("cached_tokens", 0))
    if not any((input_tokens, output_tokens, cached)):
        return None
    metadata: dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    if cached:
        metadata["input_token_details"] = {"cache_read": cached}
    return metadata
