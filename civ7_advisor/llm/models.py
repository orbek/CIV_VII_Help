from __future__ import annotations

from dataclasses import dataclass, field

# Status vocabulary for CommentaryResult, and what each one promises the UI:
#   disabled   — no local model is configured; the deterministic advice is all there is.
#   idle       — nothing to narrate yet (no complete turn, or no insights this turn).
#   queued     — accepted, waiting behind another generation. NOT yet running.
#   generating — a request is running right now.
#   ready      — `commentary` is present and its identity matches what was asked for.
#   error      — the generation failed; `message` says so and the advice stands alone.
STATUSES = ("disabled", "idle", "queued", "generating", "ready", "error")


@dataclass(frozen=True)
class Explanation:
    insight_id: str
    text: str


@dataclass(frozen=True)
class PlanStep:
    insight_id: str
    step: str


@dataclass(frozen=True)
class CommentaryIdentity:
    """Exactly which decision context a generation was produced from.

    Generated prose may only be shown beside the advice it was actually written about.
    Every input that can change the recommendation appears here, so the UI can compare
    rather than assume: if any field differs from the current snapshot the prose is
    history, not an explanation of what is on screen now. `decision_revision`,
    `context_revision` and `catalog_revision` are placeholders until phases 2 and 3
    publish decisions, accepted player context and the reviewed guide catalog; they are
    part of the contract now so nothing has to be re-plumbed to start populating them.
    """

    session: str                      # the store epoch's session id
    epoch: int
    evidence_mode: str                # "oracle" | "fair" — what the prompt was allowed to read
    snapshot_revision: int
    turn: int
    insight_ids: tuple[str, ...] = ()  # the insights this generation was given, in rank order
    # A fingerprint of the decisions on screen — their ids, their preferred actions and
    # the evidence behind them — rather than a counter. A counter would only tell us
    # something changed; this tells us whether *this* prose was written about *these*
    # recommendations, which is what decides whether it may be shown as their explanation.
    decision_revision: str = ""
    context_revision: int = 0
    catalog_revision: str = ""

    def matches(self, other: CommentaryIdentity | None) -> bool:
        return other is not None and self == other

    def same_session(self, other: CommentaryIdentity | None) -> bool:
        """Same sitting and same evidence mode — the only case where older prose may be
        shown at all, and then only clearly dated and never as the current explanation."""
        return (other is not None and self.session == other.session
                and self.epoch == other.epoch and self.evidence_mode == other.evidence_mode)


@dataclass(frozen=True)
class Commentary:
    model: str
    prompt_hash: str
    turn: int
    saw_oracle: bool
    second_opinion: str
    explain: tuple[Explanation, ...]
    turn_plan: tuple[PlanStep, ...]
    identity: CommentaryIdentity | None = None


@dataclass(frozen=True)
class CommentaryResult:
    status: str  # one of STATUSES
    turn: int | None
    message: str
    commentary: Commentary | None = None
    # A ready generation from earlier in this same session and evidence mode, kept only
    # so the UI can offer it as dated history while a new one runs. Never the current
    # explanation: its identity is, by construction, not the current one.
    previous: Commentary | None = field(default=None)
