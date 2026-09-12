"""Small builders for hand-made GameStates in advisor tests."""
from __future__ import annotations

from civ_advisor.advisors.base import Insight, Provenance, Severity
from civ_advisor.ingest.events import Combatant, CombatRow, DiplomacySummaryRow, GossipRow
from civ_advisor.ingest.production import BuildQueueRow
from civ_advisor.ingest.readers import DiplomacyRow, HistorianRow, IntentKind, TargetRow
from civ_advisor.ingest.textlogs import DealItem
from civ_advisor.state.models import GameState, Player, PlayerKind, PlayerTurn, StrategyStatus
from civ_advisor.store import SCHEMA_VERSION, Snapshot, _coverage


def insight(
    id: str = "x", advisor: str = "threat", severity: Severity = Severity.INFO,
    provenance: Provenance = Provenance.FAIR, turn: int = 10, **kw,
) -> Insight:
    return Insight(
        id=id, advisor=advisor, severity=severity, provenance=provenance,
        title=kw.get("title", id), recommendation=kw.get("recommendation", "do it"),
        why=kw.get("why", "because"), turn=turn, subject_player=kw.get("subject_player"),
    )


def player_turn(turn: int, player: int, **overrides) -> PlayerTurn:
    base = dict(
        turn=turn, player=player, cities=1, towns=1, settlement_cap=4, settlements_over_cap=0,
        urban_pop=5, rural_pop=10, techs=8, land_units=5, naval_units=0, tiles_owned=40,
        tiles_improved=10, gold_balance=100.0, science=20.0, culture=20.0, gold=20.0,
        production=20.0, food=20.0, happiness=10.0, diplomacy=5.0,
    )
    base.update(overrides)
    return PlayerTurn(**base)


def game_state(
    turn: int = 10,
    rivals: dict[int, str] | None = None,
    human_stats: dict | None = None,
    rival_stats: dict[int, dict] | None = None,
    history_turns: int = 1,
) -> GameState:
    """A game whose complete turn is `turn` (latest is turn + 1).

    Every rival and the human get identical default stats (see player_turn) unless
    overridden. `history_turns` copies of those stats are written for the turns
    ending at `turn`, so GameState.series() has data.
    """
    rivals = {1: "Rival One"} if rivals is None else rivals
    state = GameState(latest_turn=turn + 1, complete_through_turn=turn)
    state.players[0] = Player(0, "You", PlayerKind.HUMAN, True, turn + 1)
    for pid, name in rivals.items():
        state.players[pid] = Player(pid, name, PlayerKind.RIVAL, True, turn)
    for t in range(turn - history_turns + 1, turn + 1):
        state.turns[t] = {0: player_turn(t, 0, **(human_stats or {}))}
        for pid in rivals:
            state.turns[t][pid] = player_turn(t, pid, **((rival_stats or {}).get(pid, {})))
    return state


def scored_war(turn: int, actor: int, target: int | None = 0, score: float = 202.0) -> DiplomacyRow:
    return DiplomacyRow(turn, actor, "DECLARE_WAR", target, IntentKind.SCORED, score)


def executed_war(turn: int, actor: int, target: int | None = 0) -> DiplomacyRow:
    return DiplomacyRow(turn, actor, "DECLARE_WAR", target, IntentKind.EXECUTED, None)


def kill(turn: int, victim: int, killer: int, unit: str = "Warrior", x: int = 10, y: int = 10) -> HistorianRow:
    return HistorianRow("UNIT_KILLED", "AGE_ANTIQUITY", turn, x, y, victim, killer, unit, None)


def city_target(
    turn: int, player: int, owner: int = 0, x: int = 10, y: int = 10,
    target_type: str = "TARGET_ENEMY_CITY",
) -> TargetRow:
    return TargetRow(turn, player, target_type, owner, 1, x, y)


def strategy(player: int, path: str, weight: int, status: str = "Following", since: int = 1) -> StrategyStatus:
    return StrategyStatus(player=player, strategy=path, status=status, since_turn=since, weight=weight)


def build_queue_row(turn: int, player: int, city: str = "LOC_CITY_NAME_TEST1", item: str = "BUILDING_BRICKYARD",
                    added: float = 10.0, current: float = 0.0, needed: float = 50.0) -> BuildQueueRow:
    return BuildQueueRow(turn, player, city, added, item, current, needed, 0.0)


def combat(turn: int, att_player: int, def_player: int, destroyed: str | None = None,
           att_kind: str = "UNIT_WARRIOR", def_kind: str = "UNIT_SPEARMAN", x: int = 10, y: int = 10) -> CombatRow:
    return CombatRow(turn, "Unit vs Unit", x, y, att_player, def_player, "Melee",
                     Combatant(100, att_kind), Combatant(200, def_kind),
                     20, 20, 0, 0, 30, 30, destroyed, 0, "(70)100", "(70)100")


def gossip_row(turn: int, leader: str, civilization: str, type: str = "GOSSIP_UNIT_DESTROYED",
               x: int = 10, y: int = 10, detail: str | None = None) -> GossipRow:
    return GossipRow(turn, leader, civilization, x, y, type, detail)


def diplo_event(turn: int, initiator: int, recipient: int, action: str = "Denounce",
                details: str = "", mayhem: float | None = None,
                visibility: str | None = None) -> DiplomacySummaryRow:
    return DiplomacySummaryRow(turn, initiator, recipient, action, details, mayhem, visibility)


def deal(turn: int, from_player: int, to_player: int, kind: str = "Peace") -> DealItem:
    return DealItem(turn, 1, from_player, to_player, kind, 0, 1)


def snapshot(
    state: GameState, insights=None, session: str = "session-1", epoch: int = 1,
    revision: int = 1, captured_at: float = 0.0,
) -> Snapshot:
    """A published snapshot around a hand-made state, for worker and serializer tests."""
    from civ_advisor.advisors import run_all

    ranked = run_all(state) if insights is None else list(insights)
    return Snapshot(
        schema_version=SCHEMA_VERSION, session=session, epoch=epoch,
        epoch_reason="first_load", game_key=None, revision=revision,
        captured_at=captured_at, latest_turn=state.latest_turn,
        analysis_turn=state.complete_through_turn, state=state, insights=tuple(ranked),
        coverage=_coverage(state, state.complete_through_turn),
    )
