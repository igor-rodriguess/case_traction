"""Janela temporal explícita de uma execução observável."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RunTiming(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    started_at: datetime
    finished_at: datetime
    duration_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_window(self) -> "RunTiming":
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise ValueError("Run timestamps devem possuir timezone.")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at não pode anteceder started_at.")
        expected = (self.finished_at - self.started_at).total_seconds() * 1000
        if abs(expected - self.duration_ms) > 1:
            raise ValueError("duration_ms deve ser derivada dos timestamps.")
        return self

    @classmethod
    def between(cls, started_at: datetime, finished_at: datetime) -> "RunTiming":
        return cls(started_at=started_at, finished_at=finished_at, duration_ms=round((finished_at - started_at).total_seconds() * 1000, 3))
