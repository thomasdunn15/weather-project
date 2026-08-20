"""Claude transport seam — every LLM call in the engine goes through here.

Two backends implement the `Completer` protocol:

- `ClaudeClient` — metered Anthropic API (anthropic SDK). Reliability path
  for the automated/money-critical entrypoints (B2 copilot cron, B3 live
  experiment).
- `ClaudeCodeCompleter` — Claude Code CLI in headless mode (`claude -p`),
  billed to the operator's Claude subscription. For human-triggered research
  (B1 expansion) so it costs nothing beyond the plan.

`completer_for(entrypoint)` picks the backend per entrypoint, overridable via
the REASONING_BACKEND env var. Model tiering is CONFIG, not hardcoded:
`ModelsConfig` maps agent roles to model ids and any call can override the
model. Nothing is imported or connected at module import time; IO lives only
inside the two backends (network / subprocess respectively).
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Mapping
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from weather_markets.reasoning.contracts import MasterOutput, parse_json_payload

Role = Literal["specialist", "debate", "master"]
Backend = Literal["api", "claude_code"]


class ModelsConfig(BaseModel):
    specialist: str = "claude-haiku-4-5"  # fast/cheap default
    debate: str = "claude-sonnet-5"  # mid
    master: str = "claude-opus-4-8"  # strong

    def for_role(self, role: Role) -> str:
        return getattr(self, role)


# Subscription tiers: a Pro plan doesn't include Opus, so the CLI path must
# not hard-require it. Override per tier by passing your own ModelsConfig.
SUBSCRIPTION_MODELS = ModelsConfig(master="claude-sonnet-5")


class Completer(Protocol):
    """What the engine needs from an LLM. Both backends implement it; tests
    inject scripted fakes."""

    def complete(self, prompt: str, *, role: Role, system: str | None = None) -> str: ...


class CompletionRefused(RuntimeError):
    """Claude declined the request (stop_reason == 'refusal')."""


class ClaudeClient:
    """Metered API backend. Key resolution: explicit arg > `anthropic_api_key`
    in Settings (gitignored .env) > SDK default env resolution."""

    def __init__(
        self,
        models: ModelsConfig | None = None,
        api_key: str | None = None,
        max_tokens: int = 16000,
    ) -> None:
        self.models = models or ModelsConfig()
        self.max_tokens = max_tokens
        self._api_key = api_key
        self._client: Any = None  # anthropic.Anthropic, created lazily

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic  # deferred so importing the engine never touches the network

            key = self._api_key or _settings_field("anthropic_api_key")
            self._client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        return self._client

    def complete(
        self,
        prompt: str,
        *,
        role: Role,
        system: str | None = None,
        model: str | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": model or self.models.for_role(role),
            "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system is not None:
            kwargs["system"] = system
        if role != "specialist":
            # Adaptive thinking for the mid/strong tiers. Not sent for the
            # specialist tier: Haiku 4.5 predates adaptive thinking (400s).
            kwargs["thinking"] = {"type": "adaptive"}
        response = self._get_client().messages.create(**kwargs)
        if response.stop_reason == "refusal":
            raise CompletionRefused(f"model refused ({role} role)")
        return "".join(b.text for b in response.content if b.type == "text")


# (returncode, stdout, stderr) — injectable so tests never spawn the CLI
CliRunner = Callable[[list[str]], tuple[int, str, str]]

_JSON_ONLY = (
    "\n\nTransport note: reply with ONLY the JSON object — no prose, no "
    "markdown fences, nothing before or after it."
)


class CliCompleterError(RuntimeError):
    """The claude CLI failed, or its output broke the JSON contract twice."""


class ClaudeCodeCompleter:
    """Subscription backend: each completion shells out to the Claude Code CLI
    in headless mode (`claude -p ... --output-format json --model <model>`).

    Auth: CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`), taken from the
    process env or injected from the gitignored .env via Settings. The CLI
    can't force tool calls, so JSON contracts (per role, default: the master's
    `MasterOutput`) are enforced by instruction + parse + one corrective retry
    against the same pydantic models the API path uses.
    """

    def __init__(
        self,
        models: ModelsConfig | None = None,
        runner: CliRunner | None = None,
        claude_bin: str = "claude",
        timeout: float = 600.0,
        json_contracts: Mapping[Role, type[BaseModel]] | None = None,
    ) -> None:
        self.models = models or SUBSCRIPTION_MODELS.model_copy()
        self.claude_bin = claude_bin
        self.timeout = timeout
        self._runner: CliRunner = runner if runner is not None else self._run_subprocess
        self._json_contracts: dict[Role, type[BaseModel]] = (
            dict(json_contracts) if json_contracts is not None else {"master": MasterOutput}
        )

    def complete(
        self,
        prompt: str,
        *,
        role: Role,
        system: str | None = None,
        model: str | None = None,
    ) -> str:
        schema = self._json_contracts.get(role)
        if schema is None:
            return self._invoke(prompt, role=role, system=system, model=model)

        text = self._invoke(prompt + _JSON_ONLY, role=role, system=system, model=model)
        try:
            parse_json_payload(text, schema)
            return text
        except ValueError as first_error:
            retry_prompt = (
                f"{prompt}{_JSON_ONLY}\n\nYour previous reply was rejected: "
                f"{first_error}\nReply again with ONLY the corrected JSON object."
            )
            text = self._invoke(retry_prompt, role=role, system=system, model=model)
            try:
                parse_json_payload(text, schema)
            except ValueError as exc:
                raise CliCompleterError(
                    f"output still invalid after retry ({role} role): {exc}"
                ) from exc
            return text

    def _invoke(self, prompt: str, *, role: Role, system: str | None, model: str | None) -> str:
        argv = [
            self.claude_bin,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--model",
            model or self.models.for_role(role),
        ]
        if system is not None:
            argv += ["--system-prompt", system]
        returncode, stdout, stderr = self._runner(argv)
        if returncode != 0:
            raise CliCompleterError(
                f"claude CLI exited {returncode} ({role} role): {stderr.strip()[:500]}"
            )
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise CliCompleterError(
                f"claude CLI emitted a non-JSON envelope: {stdout[:200]!r}"
            ) from exc
        if envelope.get("is_error") or "result" not in envelope:
            raise CliCompleterError(f"claude CLI error result: {str(envelope)[:500]}")
        return str(envelope["result"])

    def _run_subprocess(self, argv: list[str]) -> tuple[int, str, str]:
        env = dict(os.environ)
        if "CLAUDE_CODE_OAUTH_TOKEN" not in env:
            token = _settings_field("claude_code_oauth_token")
            if token:
                env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=self.timeout, env=env
        )
        return proc.returncode, proc.stdout, proc.stderr


# Per-entrypoint backend defaults. Money-critical/automated paths stay on the
# metered API; human-triggered research rides the subscription.
_DEFAULT_BACKENDS: dict[str, Backend] = {
    "expansion": "claude_code",  # B1 — human-triggered research
    "copilot": "api",  # B2 — cron digest
    "advisor": "api",  # B3 — live experiment
}


def completer_for(
    entrypoint: str,
    models: ModelsConfig | None = None,
    env: Mapping[str, str] | None = None,
) -> Completer:
    """Pick the backend for an entrypoint; REASONING_BACKEND env var overrides."""
    environ = os.environ if env is None else env
    override = environ.get("REASONING_BACKEND")
    if override is None and entrypoint not in _DEFAULT_BACKENDS:
        raise ValueError(
            f"unknown entrypoint {entrypoint!r}: add it to _DEFAULT_BACKENDS "
            "or set REASONING_BACKEND=api|claude_code"
        )
    backend = override or _DEFAULT_BACKENDS[entrypoint]
    if backend == "claude_code":
        return ClaudeCodeCompleter(models=models)
    if backend == "api":
        return ClaudeClient(models=models)
    raise ValueError(f"REASONING_BACKEND must be 'api' or 'claude_code', got {backend!r}")


def _settings_field(name: str) -> str | None:
    try:
        from weather_markets.config import settings

        return getattr(settings, name)
    except Exception:
        return None  # outside the repo env; callers fall back to process env
