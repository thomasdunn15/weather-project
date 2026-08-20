"""Reusable matrix -> specialists -> debate -> master reasoning engine.

Pure at import time: no network, no DB, no subprocess, no trading side
effects. IO lives only in Retriever backends and the two Completer backends
(API `ClaudeClient`, subscription `ClaudeCodeCompleter`), all injected.
"""

from weather_markets.reasoning.client import (
    SUBSCRIPTION_MODELS,
    Backend,
    ClaudeClient,
    ClaudeCodeCompleter,
    CliCompleterError,
    Completer,
    CompletionRefused,
    ModelsConfig,
    Role,
    completer_for,
)
from weather_markets.reasoning.contracts import Claim, MasterOutput, parse_json_payload
from weather_markets.reasoning.engine import (
    DebateLayer,
    Decision,
    EngineResult,
    MasterAgent,
    ReasoningEngine,
    SpecialistAgent,
    SpecialistReport,
)
from weather_markets.reasoning.matrix import FocusPoint, Matrix, SubPoint
from weather_markets.reasoning.retriever import Chunk, MockRetriever, Retriever

__all__ = [
    "SUBSCRIPTION_MODELS",
    "Backend",
    "Chunk",
    "Claim",
    "ClaudeClient",
    "ClaudeCodeCompleter",
    "CliCompleterError",
    "Completer",
    "CompletionRefused",
    "DebateLayer",
    "Decision",
    "EngineResult",
    "FocusPoint",
    "MasterAgent",
    "MasterOutput",
    "Matrix",
    "MockRetriever",
    "ModelsConfig",
    "ReasoningEngine",
    "Retriever",
    "Role",
    "SpecialistAgent",
    "SpecialistReport",
    "SubPoint",
    "completer_for",
    "parse_json_payload",
]
