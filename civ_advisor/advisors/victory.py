"""AI strategic focus and broad output proxies; these are not current victory scores."""
from __future__ import annotations

from civ_advisor.state.models import GameState, Player, StrategyStatus

from .base import Insight, Provenance, Severity

STRATEGY_COMMITTED = 75  # AI strategy weight at/above which we call the AI "committed"
LEAD_MARGIN = 1.25       # broad output must beat the runner-up by this factor to flag a large gap

# AI strategy category -> (PlayerTurn attribute used as a broad output proxy, label)
PATH_STATS: dict[str, tuple[str, str]] = {
    "SCIENCE": ("science", "science yield"),
    "CULTURAL": ("culture", "culture yield"),
    "ECONOMIC": ("gold", "gold yield"),
    "MILITARY": ("military_units", "military units"),
}


def leaderboards(state: GameState) -> dict[str, list[tuple[Player, float]]]:
    """Per path, alive majors (human included) ordered best-first by the proxy stat."""
    t = state.complete_through_turn
    boards: dict[str, list[tuple[Player, float]]] = {}
    for path, (attr, _) in PATH_STATS.items():
        rows = [
            (p, float(getattr(state.at(p.id, t), attr)))
            for p in state.majors() if state.at(p.id, t) is not None
        ]
        boards[path] = sorted(rows, key=lambda pv: pv[1], reverse=True)
    return boards


def committed_paths(state: GameState) -> dict[tuple[int, str], StrategyStatus]:
    """(rival id, category) -> every strongly weighted AI strategic focus."""
    out: dict[tuple[int, str], StrategyStatus] = {}
    for rival in state.rivals():
        for path, st in state.strategies.get(rival.id, {}).items():
            if path in PATH_STATS and st.following and st.weight >= STRATEGY_COMMITTED:
                out[(rival.id, path)] = st
    return out


def advise(state: GameState) -> list[Insight]:
    t = state.complete_through_turn
    out: list[Insight] = []
    committed = committed_paths(state)

    for (pid, path), st in sorted(committed.items()):
        rival = state.players[pid]
        label = PATH_STATS[path][1]
        out.append(Insight(
            id=f"victory.pursuing.{pid}.{path}", advisor="victory",
            severity=Severity.INFO, provenance=Provenance.ORACLE,
            title=f"{rival.name}'s AI is focused on {path.title()}",
            recommendation=f"Expect more emphasis on {label}; compare their actual victory score in-game "
                           f"before deciding whether to compete or interfere.",
            why=f"{rival.name}'s AI is following its {path} strategy at weight {st.weight}, "
                f"last changed on turn {st.since_turn} (focus threshold {STRATEGY_COMMITTED}).",
            turn=t, subject_player=pid,
        ))

    for path, board in leaderboards(state).items():
        if len(board) < 2:
            continue
        (leader, lv), (second, sv) = board[0], board[1]
        _, label = PATH_STATS[path]
        if leader.id == state.HUMAN:
            if lv > sv:
                out.append(Insight(
                    id=f"victory.you_lead.{path}", advisor="victory",
                    severity=Severity.INFO, provenance=Provenance.FAIR,
                    title=f"You lead the field in {label}",
                    recommendation=f"Use this output advantage, but check the current victory screen; {label} is a proxy, not victory progress.",
                    why=f"Turn {t}: you {lv:.1f} vs {second.name} {sv:.1f}.",
                    turn=t, subject_player=state.HUMAN,
                ))
            continue
        if lv > 0 and lv >= LEAD_MARGIN * sv:
            ratio = f" ({lv / sv:.2f}x)" if sv else ""
            # The yield lead and the AI's commitment to the path are two separate
            # insights on purpose. Folding the commitment into this one escalated it
            # to ORACLE, so with the Oracle toggle off the lead itself disappeared —
            # deleting evidence the player *can* see (it is in the leaderboard table
            # right below) exactly when it matters most. This one stays FAIR and
            # quotes only the yields; the commitment gets its own ORACLE insight.
            out.append(Insight(
                id=f"victory.leader.{path}", advisor="victory",
                severity=Severity.ADVISE, provenance=Provenance.FAIR,
                title=f"{leader.name} has a large {label} advantage",
                recommendation=f"Check whether that output is translating into current victory score before "
                               f"spending resources to contest {leader.name}.",
                why=f"Turn {t}: {leader.name} {lv:.1f} vs runner-up {second.name} {sv:.1f}{ratio}.",
                turn=t, subject_player=leader.id,
            ))
            st = committed.get((leader.id, path))
            if st:
                out.append(Insight(
                    id=f"victory.leader_committed.{path}", advisor="victory",
                    severity=Severity.WARN, provenance=Provenance.ORACLE,
                    title=f"{leader.name}'s {path.title()} focus matches their output lead",
                    recommendation=f"The focus and output point the same way. Verify {leader.name}'s actual "
                                   f"victory score in-game, then decide whether intervention is warranted.",
                    why=f"{leader.name}'s AI is following its {path} strategy at weight {st.weight} "
                        f"(focus threshold {STRATEGY_COMMITTED}), last changed on turn {st.since_turn}.",
                    turn=t, subject_player=leader.id,
                ))
    return out
