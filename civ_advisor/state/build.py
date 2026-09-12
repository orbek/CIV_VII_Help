"""Turn raw log rows into a GameState for the current game."""
from __future__ import annotations

from dataclasses import asdict

from civ_advisor.games.base import GameProfile
from civ_advisor.ingest.load import RawLogs

from .models import GameState, Player, PlayerKind, PlayerTurn, StrategyStatus
from .names import NameResolver

INDEPENDENT_KEY = "LOC_CIVILIZATION_INDEPENDENT_NAME"

# Levels a PlayerIdentityRow can carry (spec §5). Civ VII's own identities never
# set `level` to anything but FULL_CIV, so this only takes effect for a game (Civ
# VI) whose GameCore.log distinguishes majors from city-states, Free Cities and
# the barbarian slot.
LEVEL_INDEPENDENT = {"CIVILIZATION_LEVEL_CITY_STATE", "CIVILIZATION_LEVEL_FREE_CITIES"}
LEVEL_TRIBE = "CIVILIZATION_LEVEL_TRIBE"

LEADER_NAMES = {
    "LOC_LEADER_IBN_BATTUTA_NAME": "Ibn Battuta",
    "LOC_LEADER_HARRIET_TUBMAN_NAME": "Harriet Tubman",
    "LOC_LEADER_NAPOLEON_NAME": "Napoleon",
    "LOC_LEADER_NAPOLEON_ALT_NAME": "Napoleon, Revolutionary",
    "LOC_LEADER_JOSE_RIZAL_NAME": "José Rizal",
    "LOC_LEADER_TRUNG_TRAC_NAME": "Trưng Trắc",
    "LOC_LEADER_CONFUCIUS_NAME": "Confucius",
    "LOC_LEADER_CATHERINE_NAME": "Catherine",
    "LOC_LEADER_ADA_LOVELACE_NAME": "Ada Lovelace",
    "LOC_LEADER_AMINA_NAME": "Amina",
    "LOC_LEADER_ASHOKA_NAME": "Ashoka",
    "LOC_LEADER_AUGUSTUS_NAME": "Augustus",
    "LOC_LEADER_BENJAMIN_FRANKLIN_NAME": "Benjamin Franklin",
    "LOC_LEADER_CHARLEMAGNE_NAME": "Charlemagne",
    "LOC_LEADER_FRIEDRICH_NAME": "Friedrich",
    "LOC_LEADER_GENGHIS_KHAN_NAME": "Genghis Khan",
    "LOC_LEADER_HATSHEPSUT_NAME": "Hatshepsut",
    "LOC_LEADER_HIMIKO_NAME": "Himiko",
    "LOC_LEADER_ISABELLA_NAME": "Isabella",
    "LOC_LEADER_LAFAYETTE_NAME": "Lafayette",
    "LOC_LEADER_MACHIAVELLI_NAME": "Machiavelli",
    "LOC_LEADER_PACHACUTI_NAME": "Pachacuti",
    "LOC_LEADER_SIMON_BOLIVAR_NAME": "Simón Bolívar",
    "LOC_LEADER_TECUMSEH_NAME": "Tecumseh",
    "LOC_LEADER_XERXES_NAME": "Xerxes",
}


def display_name(key: str) -> str:
    """Map a LOC_LEADER_*_NAME key to a display name; unknown keys are title-cased."""
    if key in LEADER_NAMES:
        return LEADER_NAMES[key]
    core = key.removeprefix("LOC_LEADER_").removeprefix("LOC_").removesuffix("_NAME")
    return core.replace("_", " ").title()


def _identity_name(key: str) -> str:
    return display_name(f"LOC_{key}_NAME")


def _civilization_name(key: str) -> str:
    return key.removeprefix("CIVILIZATION_").replace("_", " ").title()


def build_state(raw: RawLogs, profile: GameProfile | None = None) -> GameState:
    state = GameState(files=dict(raw.files))
    if not raw.stats:
        return state

    state.latest_turn = max(r.turn for r in raw.stats)
    state.complete_through_turn = max(state.latest_turn - 1, 0)

    # Per-turn stats, with treasury and happiness merged on (turn, player).
    treasury = {(r.turn, r.player): r for r in raw.treasury}
    happiness = {(r.turn, r.player): r for r in raw.happiness}
    for s in raw.stats:
        extra: dict = {}
        tr = treasury.get((s.turn, s.player))
        if tr is not None:
            extra |= dict(
                unit_maintenance=tr.unit_maintenance,
                building_maintenance=tr.building_maintenance,
                total_maintenance=tr.total_maintenance,
            )
        hp = happiness.get((s.turn, s.player))
        if hp is not None:
            extra |= dict(golden_age=hp.golden_age, happiness_threshold=hp.threshold, happiness_total=hp.total)
        state.turns.setdefault(s.turn, {})[s.player] = PlayerTurn(**asdict(s), **extra)

    # Players: 0 is human; a LOC_LEADER owner key or a happiness row marks a rival;
    # everyone else is an independent people. Where a game's identities carry a
    # `level` (Civ VI does; Civ VII's is always FULL_CIV), that level classifies
    # city-states, Free Cities and the barbarian slot directly rather than
    # falling through Civ VII's owner-key/happiness heuristics, which Civ VI's
    # logs cannot supply at all.
    owner_keys = {r.player: r.owner_key for r in raw.victories}
    identities = {r.player: r for r in raw.player_identities}
    happiness_players = {r.player for r in raw.happiness}
    last_seen: dict[int, int] = {}
    for s in raw.stats:
        last_seen[s.player] = max(last_seen.get(s.player, 0), s.turn)
    for pid, seen in sorted(last_seen.items()):
        identity = identities.get(pid)
        if identity is not None and identity.level == LEVEL_TRIBE:
            # The barbarian slot is not a player at all, regardless of what any
            # other log (even a future one) reports about it.
            continue
        key = owner_keys.get(pid)
        identity_is_major = identity is not None and identity.level == "CIVILIZATION_LEVEL_FULL_CIV"
        identity_is_independent = identity is not None and identity.level in LEVEL_INDEPENDENT
        has_leader_key = key is not None and key != INDEPENDENT_KEY
        if pid == GameState.HUMAN:
            kind, name = PlayerKind.HUMAN, "You"
        elif identity_is_independent:
            kind, name = PlayerKind.INDEPENDENT, f"Independent {pid}"
        elif identity_is_major or has_leader_key or pid in happiness_players:
            kind = PlayerKind.RIVAL
            name = (_identity_name(identity.leader) if identity_is_major and identity.leader
                    else display_name(key) if has_leader_key else f"Player {pid}")
        else:
            kind, name = PlayerKind.INDEPENDENT, f"Independent {pid}"
        state.players[pid] = Player(
            id=pid, name=name, kind=kind,
            alive=seen >= state.complete_through_turn, last_seen_turn=seen,
        )

    # Strategies are change events; fold them in turn order to the current status.
    for v in sorted(raw.victories, key=lambda r: r.turn):
        state.strategies.setdefault(v.player, {})[v.strategy] = StrategyStatus(
            player=v.player, strategy=v.strategy, status=v.status, since_turn=v.turn, weight=v.weight,
        )

    state.identities = dict(identities)
    state.intents = list(raw.diplomacy)
    state.targets = list(raw.targets)
    state.events = list(raw.historian)
    state.build_queues = list(raw.build_queue)
    state.combats = list(raw.combat)
    state.gossip = list(raw.gossip)
    state.diplomacy_events = list(raw.diplomacy_summary)
    state.deals = list(raw.deals)
    state.unit_operations = list(raw.unit_operations)
    state.tactical = list(raw.tactical)
    state.operations = list(raw.operations)
    state.combat_orders = list(raw.combat_orders)
    state.operation_evals = list(raw.operation_evals)
    state.unit_efficiency = list(raw.unit_efficiency)
    state.mayhem = list(raw.mayhem)
    state.commander_promotions = list(raw.commander_promotions)
    for d in raw.deals:
        if d.is_peace:
            pair = d.parties()
            state.peace_turns[pair] = max(state.peace_turns.get(pair, 0), d.turn)
    state.names = NameResolver.build(
        rival_names={p.id: p.name for p in state.players.values() if p.kind is PlayerKind.RIVAL},
        human_city_keys=[q.city for q in raw.build_queue if q.player == GameState.HUMAN],
        player_leaders={r.player: _identity_name(r.leader) for r in raw.player_identities if r.leader},
        player_civilizations={r.player: _civilization_name(r.civilization)
                              for r in raw.player_identities},
    )
    return state
