from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Explanation:
    insight_id: str
    text: str


@dataclass(frozen=True)
class PlanStep:
    insight_id: str
    step: str


@dataclass(frozen=True)
class Commentary:
    model: str
    prompt_hash: str
    turn: int
    saw_oracle: bool
    second_opinion: str
    explain: tuple[Explanation, ...]
    turn_plan: tuple[PlanStep, ...]


@dataclass(frozen=True)
class CommentaryResult:
    status: str  # idle | generating | ready | disabled | error
    turn: int | None
    message: str
    commentary: Commentary | None = None
