"""Shared JSON contracts between the engine and transport backends.

The master's output shape lives here so both transports validate against the
same pydantic models — the API `ClaudeClient` (prompt-instructed JSON, parsed
by the engine) and the CLI `ClaudeCodeCompleter` (instruct + parse + one
retry). Same contract, different transport.
"""

from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class Claim(BaseModel):
    text: str
    chunk_ids: list[str] = []


class MasterOutput(BaseModel):
    decision: str
    claims: list[Claim] = []


def parse_json_payload(raw: str, schema: type[SchemaT]) -> SchemaT:
    """Extract the outermost JSON object from `raw` and validate it."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"output is not JSON: {raw[:200]!r}")
    try:
        return schema.model_validate(json.loads(raw[start : end + 1]))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"output failed {schema.__name__} validation: {exc}") from exc
