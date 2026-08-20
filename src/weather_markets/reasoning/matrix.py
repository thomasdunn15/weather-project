"""Typed reasoning matrix: the taxonomy of focus points that scopes retrieval.

Pure data — no IO beyond `Matrix.load()` reading a local JSON/YAML file on
explicit request.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, model_validator


class SubPoint(BaseModel):
    id: str
    name: str
    description: str = ""


class FocusPoint(BaseModel):
    id: str
    name: str
    description: str = ""
    sub_points: list[SubPoint] = []


class Matrix(BaseModel):
    name: str
    description: str = ""
    points: list[FocusPoint]

    @model_validator(mode="after")
    def _validate(self) -> "Matrix":
        if not self.points:
            raise ValueError("matrix needs at least one focus point")
        seen: set[str] = set()
        for point_id in self.all_ids():
            if point_id in seen:
                raise ValueError(f"duplicate matrix id: {point_id!r}")
            seen.add(point_id)
        return self

    def all_ids(self) -> list[str]:
        return [
            i
            for p in self.points
            for i in [p.id, *(s.id for s in p.sub_points)]
        ]

    def scope_for(self, point: FocusPoint) -> list[str]:
        """The retrieval scope for one specialist: the point + its sub-points."""
        return [point.id, *(s.id for s in point.sub_points)]

    @classmethod
    def load(cls, path: str | Path) -> "Matrix":
        p = Path(path)
        text = p.read_text()
        if p.suffix in {".yaml", ".yml"}:
            import yaml

            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
        return cls.model_validate(data)
