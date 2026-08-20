"""Backend tests: Claude Code CLI completer (mocked subprocess) + routing."""

from __future__ import annotations

import json

import pytest

from weather_markets.reasoning import (
    SUBSCRIPTION_MODELS,
    ClaudeClient,
    ClaudeCodeCompleter,
    CliCompleterError,
    ModelsConfig,
    completer_for,
)


def envelope(result: str) -> str:
    return json.dumps(
        {"type": "result", "subtype": "success", "is_error": False, "result": result}
    )


MASTER_JSON = json.dumps({"decision": "go", "claims": [{"text": "t", "chunk_ids": ["c1"]}]})


class FakeRunner:
    """Scripted (returncode, stdout, stderr) per call; records every argv."""

    def __init__(self, outputs: list[tuple[int, str, str]]) -> None:
        self.outputs = list(outputs)
        self.argvs: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str, str]:
        self.argvs.append(argv)
        return self.outputs.pop(0)


def _model_arg(argv: list[str]) -> str:
    return argv[argv.index("--model") + 1]


def test_cli_command_shape_and_result():
    runner = FakeRunner([(0, envelope("hello"), "")])
    out = ClaudeCodeCompleter(runner=runner).complete("what up", role="specialist", system="sys")
    assert out == "hello"
    argv = runner.argvs[0]
    assert argv[0] == "claude"
    assert argv[1:3] == ["-p", "what up"]
    assert argv[argv.index("--output-format") + 1] == "json"
    assert _model_arg(argv) == "claude-haiku-4-5"  # specialist tier
    assert argv[argv.index("--system-prompt") + 1] == "sys"


def test_cli_subscription_master_defaults_to_sonnet_not_opus():
    assert SUBSCRIPTION_MODELS.master == "claude-sonnet-5"
    runner = FakeRunner([(0, envelope(MASTER_JSON), "")])
    ClaudeCodeCompleter(runner=runner).complete("q", role="master")
    assert _model_arg(runner.argvs[0]) == "claude-sonnet-5"


def test_cli_per_tier_and_per_call_model_overrides():
    runner = FakeRunner([(0, envelope(MASTER_JSON), ""), (0, envelope(MASTER_JSON), "")])
    completer = ClaudeCodeCompleter(models=ModelsConfig(master="claude-opus-4-8"), runner=runner)
    completer.complete("q", role="master")
    completer.complete("q", role="master", model="claude-haiku-4-5")
    assert _model_arg(runner.argvs[0]) == "claude-opus-4-8"
    assert _model_arg(runner.argvs[1]) == "claude-haiku-4-5"


def test_cli_master_json_instruction_retry_then_success():
    runner = FakeRunner(
        [(0, envelope("sure! json coming right up"), ""), (0, envelope(MASTER_JSON), "")]
    )
    out = ClaudeCodeCompleter(runner=runner).complete("decide", role="master")
    assert out == MASTER_JSON
    assert len(runner.argvs) == 2
    first_prompt, retry_prompt = runner.argvs[0][2], runner.argvs[1][2]
    assert "ONLY the JSON object" in first_prompt
    assert "rejected" in retry_prompt and "decide" in retry_prompt


def test_cli_master_json_retry_exhausted_raises():
    runner = FakeRunner([(0, envelope("nope"), ""), (0, envelope("still nope"), "")])
    with pytest.raises(CliCompleterError, match="after retry"):
        ClaudeCodeCompleter(runner=runner).complete("q", role="master")
    assert len(runner.argvs) == 2  # exactly one retry, then fail


def test_cli_non_contract_roles_return_raw_text():
    runner = FakeRunner([(0, envelope("free text, not json"), "")])
    out = ClaudeCodeCompleter(runner=runner).complete("q", role="debate")
    assert out == "free text, not json"
    assert len(runner.argvs) == 1
    assert "ONLY the JSON object" not in runner.argvs[0][2]


def test_cli_nonzero_exit_raises():
    runner = FakeRunner([(1, "", "invalid oauth token")])
    with pytest.raises(CliCompleterError, match="exited 1.*invalid oauth token"):
        ClaudeCodeCompleter(runner=runner).complete("q", role="specialist")


def test_cli_error_envelope_and_bad_envelope_raise():
    err = json.dumps({"type": "result", "is_error": True, "result": "boom"})
    runner = FakeRunner([(0, err, "")])
    with pytest.raises(CliCompleterError, match="error result"):
        ClaudeCodeCompleter(runner=runner).complete("q", role="specialist")
    runner = FakeRunner([(0, "not an envelope", "")])
    with pytest.raises(CliCompleterError, match="non-JSON envelope"):
        ClaudeCodeCompleter(runner=runner).complete("q", role="specialist")


def test_backend_routing_defaults():
    assert isinstance(completer_for("expansion", env={}), ClaudeCodeCompleter)  # B1
    assert isinstance(completer_for("copilot", env={}), ClaudeClient)  # B2
    assert isinstance(completer_for("advisor", env={}), ClaudeClient)  # B3


def test_backend_routing_env_override_and_errors():
    forced = completer_for("expansion", env={"REASONING_BACKEND": "api"})
    assert isinstance(forced, ClaudeClient)
    forced_cli = completer_for("copilot", env={"REASONING_BACKEND": "claude_code"})
    assert isinstance(forced_cli, ClaudeCodeCompleter)
    with pytest.raises(ValueError, match="unknown entrypoint"):
        completer_for("nope", env={})
    with pytest.raises(ValueError, match="REASONING_BACKEND"):
        completer_for("copilot", env={"REASONING_BACKEND": "banana"})


def test_backend_routing_passes_models_through():
    completer = completer_for("copilot", models=ModelsConfig(master="claude-sonnet-5"), env={})
    assert isinstance(completer, ClaudeClient)
    assert completer.models.master == "claude-sonnet-5"
