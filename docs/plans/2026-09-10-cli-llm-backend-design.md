# Driving ARTEMIS from a Claude Code / Codex CLI subscription

**Date:** 2026-09-10
**Status:** Implemented (runs with no API keys at all)

## Problem

ARTEMIS was Gemini-only in practice. The router already branched on
`anthropic` / `openai` / `openrouter` / `xai`, but everything around it
assumed Gemini: every node in `config/artemis.jsonc` defaulted to
`google/gemini-*`, `artemis init` wrote `ARTEMIS_DEFAULT_MODEL=gemini-2.5-flash`
whichever provider you picked, and the optional judge nodes resolved to
hardcoded Gemini defaults. Running without an API key at all was not possible.

The goal: run the agent on a **locally installed, signed-in `claude` or `codex`
CLI**, spending that subscription instead of a provider API key.

## What the CLIs can actually do

Measured against `claude` 2.1.266 and `codex-cli` 0.137.0.

| | Claude CLI | Codex CLI |
| --- | --- | --- |
| Non-interactive | `-p` | `codex exec` |
| Structured output | prompt contract + parse | `--output-schema` (hard-enforced) |
| Inline images | `--input-format stream-json`, base64 blocks | `-i FILE` |
| System prompt | `--system-prompt` (full override) | none — goes in the prompt body |
| Isolation | `--safe-mode --tools "" --strict-mcp-config --disable-slash-commands --no-session-persistence` | `--ephemeral --ignore-user-config --ignore-rules --sandbox read-only` |
| Auth | subscription OAuth (`apiKeySource: "none"`) | subscription login |
| Usage reporting | `result.usage`, `total_cost_usd`, `rate_limit_event` | `turn.completed.usage` |
| Input tokens / call | ~1,200 | ~27,800 |
| Wall clock / call | ~1.6 s | ~13.4 s |

Three findings shaped the design:

1. **`--safe-mode`, not `--bare`.** Both strip customizations, but `--bare`
   forces `ANTHROPIC_API_KEY` and never reads OAuth — it would defeat the whole
   point. `--safe-mode` disables `CLAUDE.md`, skills, plugins, hooks and MCP
   servers while leaving auth working.
2. **A full `--system-prompt` override is worth ~4.2k tokens per call.** Default
   preamble: ~4,700 input tokens for a trivial prompt. With the override plus
   `--disable-slash-commands`: 548.
3. **Neither CLI exposes native function calling.** Both run their own tool loop
   and return only a final message.

## Design

### One-shot subprocess per call

Each `_agenerate` spawns one process and passes the whole conversation. This
matches how ARTEMIS already works — nodes re-send full history every step and
compress it themselves — so per-node model configs, `LLMWithFallback` chains and
per-device concurrency all work untouched, and a retry can never corrupt session
state.

A persistent `stream-json` session was rejected: ARTEMIS rewrites its history
each turn (transcript ledger, chunking eras, `search_history`), while a
long-lived CLI session accumulates its own divergent history that ARTEMIS cannot
edit. An OpenAI-compatible local proxy was rejected too — it adds a process to
supervise and still needs the same tool-call emulation inside it.

### Tool calling as a prompt contract

`artemis/llm/cli/envelope.py` renders bound tool schemas into the system prompt
and asks for one JSON envelope:

```json
{"thought": "...", "text": "...", "tool_calls": [{"name": "click", "args": {"index": 3}}]}
```

The parse reuses `artemis/llm/structured.py`, so fences, prose padding and
trailing commas are tolerated. A reply with no `tool_calls` is a legitimate text
answer, not a failure; a call naming an unbound tool is dropped with a warning
rather than blowing up deep in the graph.

Codex gets hard enforcement via `--output-schema`, but OpenAI strict mode
requires `additionalProperties: false` on every nested object — a free-form
argument bag is impossible. So the strict variant carries `arguments` as a
JSON-encoded **string**, exactly OpenAI's native function-calling shape. The
parser accepts either form.

### Where it plugs in

`ChatClaudeCLI` and `ChatCodexCLI` subclass `BaseChatModel`, so
`RobustChatModelWrapper`, the fallback chain, `ModelFactory._cache`,
`record_llm_usage` and every graph node stay unchanged. Only five places knew
about it:

* `artemis/llm/router.py` — two `ModelProvider` members, `from_string` aliases,
  two `create_model` branches, and a per-backend timeout floor (the 60 s HTTP
  default is not a usable process ceiling).
* `artemis/config/constants.py` — the `LLMProvider` literal.
* `artemis/config/llm.py` — `validate_provider` checks for the binary, not a key.
* `artemis/interfaces/cli/commands/{init,doctor}.py` — wizard entries and health rows.
* `artemis/core/diagnostics/probes/credentials_probe.py` — a signed-in CLI is a
  credential.

`_astream` yields a single complete chunk rather than text deltas: the raw reply
is a JSON envelope, and streaming it would leak that into the live UI.

### Failure shaping

`CLIInvocationError` carries a `status_code`, which is all
`artemis.llm.reliability.classify_failure` needs to route CLI failures through
the existing retry / fallback / circuit-breaker policy: 429 for a spent
subscription window, 401 for a logged-out binary, 504 for a process timeout, 400
for a stale CLI (`"requires a newer version"` — retrying cannot fix a local
defect).

### Environment isolation

Provider API keys are stripped from the child environment, so a key sitting in
`.env` cannot silently switch a subscription call to metered API billing
(`ARTEMIS_CLI_INHERIT_API_KEYS=1` opts out). `--safe-mode --tools ""
--strict-mcp-config` also closes a recursion hazard: `artemis mcp --install
claude` writes rules telling Claude Code to drive devices through the ARTEMIS
MCP server, and a child that loaded them could call back into the task that
spawned it.

## Running with no Google key at all

The first pass kept `object_detector` on `gemini-robotics-er-2-preview` and
declared a Gemini key mandatory. Measuring the claim changed the design.

**What the measurement said.** Driving the real detector prompt (from
`object_detector.json`, `instructions` included) through the Claude CLI backend
on synthetic 1080x2340 screens:

| target | mean error (normalized) | within 5% of truth |
| --- | --- | --- |
| large, high-contrast shapes | 0.01 | 2/2 |
| dense settings rows and toggles | 0.38 | 0/5 |

The easy case is fine; the realistic one is not. 0.38 normalized is several
hundred pixels - it taps the wrong row, and reports success. Reverse-engineering
the replies showed the model flipping the axis convention between independent
per-label calls, so a named-field contract (`{"x": ..., "y": ...}`) was tried in
place of the positional `[y, x]` array. It did not help: 0.33, still 0/5, with
one reply outside the 0-1 range entirely. Point grounding is simply the one
capability that does not transfer, exactly as `config/artemis.jsonc` warned. No
prompt engineering was shipped to paper over it.

**Why a keyless run works anyway.** Grounding does not have to go through pixel
detection. Reading the Explorer tiers:

* `flash` - `engine="oneshot"`, `tools=frozenset()`. One-shot detection. This is
  the ER-dependent path.
* `pro` - `engine="loop"`, exposing `ask_perception_tool`, which fuzzy-searches
  the accessibility/OCR screen index and returns coordinates computed from each
  element's real `bounds`. The model only picks which labelled candidate
  matches; nothing guesses pixels.
* `ultra` - re-exposes `detect_objects` plus OCR tools, so it is *worse* than
  `pro` without a Google key.

So `pro` is not a degraded fallback, it is a different mechanism - and a more
robust one, since coordinates come from measured bounds. `ARTEMIS_EXPLORER_VERSION`
sits above the per-profile knobs in `ExplorerConfig.resolve`, so one env var
pins every tier.

Auditing the remaining Google touchpoints found nothing else blocking:

| touchpoint | keyless behavior |
| --- | --- |
| all 12+ LLM nodes | routed to the CLI provider |
| Operator's direct object-detection tool | defined but mounted nowhere; the Operator grounds only via `ask_explorer` |
| `get_ocr_list` (Google Vision) | auto-hidden by `_hidden_tool_names` when OCR is unconfigured |
| native Gemini Files video path | gated on `has_google_key and is_gemini_model`; falls back to the universal keyframe engine |
| `enable_grounding` (Google Search) | mapped to the Claude CLI's `--tools WebSearch` |

The shipped configs therefore keep every node - `object_detector` included - on
the CLI provider, with the Gemini ER block commented in place for anyone who
needs pixel grounding on Canvas/Compose/Flutter screens.

**A bug this exposed.** `_run_object_detection` called
`get_llm(ctx, name="object_detector")` without `is_utils=True`. That node lives
under `utils`, so the lookup raised `AttributeError`, the caller's broad
`except Exception` swallowed it, and **every detection silently ran on the
operator's model** - the configured ER detector was never used by this path. On
the default Gemini config that meant `gemini-3.8-flash` doing ER work. Fixed,
which is a behavior change for existing Gemini users: detection now uses the
`gemini-robotics-er-2-preview` they had configured all along. The fallback to
the operator model is kept for a genuinely unset detector, and
`is_spatial_grounding_model` now drives a one-time warning whenever detection
runs on a model that cannot localize, so a guess can no longer pass for a
measurement.

## Selecting a backend

`ARTEMIS_LLM_CONFIG` names a config file deep-merged over `artemis.jsonc`. An
env var rather than a CLI flag, because `artemis run` hands the task to a daemon
worker that would not receive a flag; an env var reaches every entry point —
CLI, batch, daemon worker, `doctor`.

Two latent bugs had to be fixed to make override files usable at all:

* **Optional-node overrides were silently dropped.** `_expand_default_into_nodes`
  iterated only the required nodes, so a config naming
  `validator_pixel_safety_net` or `planner_validation` changed nothing and those
  nodes kept calling their hardcoded Gemini defaults. They are now honored when
  named, and still left unset otherwise — expanding `default` into them would
  promote cheap high-frequency judges to the flagship model.
* **The `default` / `nodes` shorthand did nothing in override files.**
  `deep_merge_llm_config` merges onto an expanded `LLMConfig`, so those two keys
  were ignored by the schema. Overrides are now expanded first, which is also
  the semantics a backend switch wants: `default` lands on every node at once.

## Verification

* New unit tests across `tests/unit/test_llm_cli_backends.py`,
  `tests/unit/config/test_llm_config_override.py`,
  `tests/unit/test_init_wizard.py` and
  `tests/unit/agents/test_object_detector_routing.py`. `build_invocation` and
  `parse_output` are pure, so argv, stdin payload and recorded-transcript
  parsing are all checked without spawning a CLI or spending a subscription; a
  sweep asserts that no node of a shipped CLI config points at a keyed provider.
* Full suite: 53 failures before and after (all pre-existing on a machine with
  no `GOOGLE_API_KEY`).
* End-to-end against both real CLIs: a bound tool plus a screenshot produced a
  correctly-typed tool call, with usage recorded through `usage_metadata`; and
  the real `_run_object_detection` path returned parseable points with no Google
  key present.
