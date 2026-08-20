"""Retrieval boundary — the ONLY place IO is allowed to live.

The engine only ever sees `Chunk`s coming out of a `Retriever`. Real backends
in this repo will usually be DB queries (`weather` Postgres) or live-data/API
adapters; they implement the same protocol. `MockRetriever` ships now for
tests and demos.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from pydantic import BaseModel


class Chunk(BaseModel):
    """One piece of evidence. `tags` are matrix point / sub-point ids."""

    id: str
    text: str
    source: str
    ref: str = ""
    tags: list[str] = []


@runtime_checkable
class Retriever(Protocol):
    def retrieve(self, query: str, matrix_scope: Sequence[str]) -> list[Chunk]: ...


class MockRetriever:
    """In-memory backend: filters by matrix scope, then by naive keyword hit."""

    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self._chunks = list(chunks)

    def retrieve(self, query: str, matrix_scope: Sequence[str]) -> list[Chunk]:
        scope = set(matrix_scope)
        scoped = [c for c in self._chunks if scope & set(c.tags)]
        words = {w for w in query.lower().split() if len(w) > 3}
        hits = [c for c in scoped if any(w in c.text.lower() for w in words)]
        # ponytail: substring keyword match; a real backend replaces this with
        # actual queries (SQL, API), not a cleverer ranker here.
        return hits or scoped
