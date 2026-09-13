"""What the tuner can be asked, and what its answers are.

The shape follows civ_advisor/ruleset/base.py on purpose: a closed set of
questions with typed answers, and no `query(lua)` on the Protocol. A caller
cannot ask this package to run arbitrary code in the player's game, because
there is no method that would take it.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Protocol, runtime_checkable


# Nothing here imports civ_advisor.games. Which capabilities a tuner reading can
# back is a statement about one GAME, so it lives with that game's profile
# (civ_advisor/games/civ6/__init__.py) rather than here. Importing games.base for
# it made this module depend on a package whose __init__ imports civ6, which
# imports this module -- a real cycle that only import order was hiding.


class TunerUnavailable(StrEnum):
    """Why there is no reading. Five genuinely different situations.

    Only NOT_ENABLED is something the player can fix by changing the game. Saying the
    wrong one would send them to change a setting that is already correct -- or, for
    NO_SOCKET, a setting that does not exist in the game they are playing, or, for
    NOT_ASKED, a setting that is fine and was simply never consulted.

    Each member is a machine-readable cause a consumer branches on. A distinct cause
    carrying another cause's enum is the same defect as carrying another cause's prose,
    just harder to see: the page would act on one story while the player reads another.
    """

    NOT_ENABLED = "not_enabled"          # the socket is closed; EnableTuner is 0
    NOT_ANSWERING = "not_answering"      # enabled, but no game is running or it did not reply
    UNREACHABLE = "unreachable"          # answered, but this figure exists in no VM
    NO_SOCKET = "no_socket"              # this game has no tuner socket to enable at all
    NOT_ASKED = "not_asked"              # the socket was never contacted; this run chose not to


@dataclass(frozen=True)
class TunerReading:
    """When a reading was taken, and from which VM.

    A log row is something the game wrote on its own; this is a value we asked
    for at a moment we chose. Both facts travel with every figure, which is why
    `read_at` exists beside `turn`.

    `turn` is the turn the GAME named when it answered, never the last turn the
    logs finished. The two differ exactly when the player is mid-turn.
    """

    turn: int
    read_at: str      # ISO 8601, the wall-clock instant of the query
    state: str        # the Lua VM name, e.g. "GameCore_Tuner"

    def __post_init__(self) -> None:
        if not self.state:
            raise ValueError("a reading must name the state it was read from")
        if self.turn < 1:
            raise ValueError(
                f"a reading must name a real game turn, got {self.turn}; turn 0 is how "
                "an unset field looks, and a figure filed under the wrong turn is the "
                "one error this project must never make")


@dataclass(frozen=True)
class CityAmenities:
    """One settlement's amenities and the sources that explain them."""

    city: str
    total: int
    from_luxuries: int
    from_civics: int
    from_entertainment: int
    housing: int
    food_surplus: int

    @property
    def unexplained(self) -> int:
        """Total minus the three sources this VM exposes. May be negative.

        Deliberately NOT validated. Civ VI exposes three amenity sources here and
        has more, in both directions: unexposed positives (great people, religion)
        push this above zero, and war weariness pushes it below -- a city at war
        can report luxuries 3 and entertainment 2 against a total of 4. Raising on
        that would turn a real game state into a crashed poll. The remainder is
        reported instead, so a reader can see the sources do not add up.
        """
        return self.total - (self.from_luxuries + self.from_civics + self.from_entertainment)


@dataclass(frozen=True)
class Maintenance:
    """The gold breakdown the logs cannot supply."""

    total: int
    buildings: int
    districts: int
    units: int
    gold: int
    gold_yield: int

    @property
    def unattributed(self) -> int:
        """Total upkeep the three queried categories do not account for.

        Not validated, for the same reason as CityAmenities.unexplained: the
        claim that buildings + districts + units is exhaustive rests on ONE
        observation where all three happened to be 0, 1 and 0. The same probe
        found GetRouteMaintenance absent from this VM, which is a hint that the
        game's own total counts things it will not itemise here.
        """
        return self.total - (self.buildings + self.districts + self.units)

    @property
    def net_gold(self) -> int:
        """Gold per turn after upkeep -- the figure the profile calls impossible."""
        return self.gold_yield - self.total


@dataclass(frozen=True)
class BuildOption:
    """One thing a settlement may build, and how long it would take.

    Both halves come from the game. Neither is derivable from the ruleset,
    because the estimate depends on this settlement's production.
    """

    item: str
    turns: int

    def __post_init__(self) -> None:
        if self.turns < 0:
            raise ValueError(f"turns must not be negative, got {self.turns}")


@dataclass(frozen=True)
class SettlementOptions:
    """Everything one settlement may build right now.

    An empty tuple means the game offered nothing, which is a fact. A settlement
    that was never asked about is absent from the collection instead.
    """

    city: str
    options: tuple[BuildOption, ...]

    def offers(self, item: str) -> BuildOption | None:
        return next((o for o in self.options if o.item == item), None)


@runtime_checkable
class TunerProvider(Protocol):
    """A closed set of questions. There is deliberately no `query(lua)`."""

    @property
    def available(self) -> bool: ...
    @property
    def reason(self) -> str | None: ...
    @property
    def unavailable(self) -> TunerUnavailable | None: ...
    def reading(self) -> TunerReading | None: ...
    def amenities(self) -> tuple[CityAmenities, ...]: ...
    def maintenance(self) -> Maintenance | None: ...
    def build_options(self) -> tuple[SettlementOptions, ...]: ...


@dataclass(frozen=True)
class NullTuner:
    """No readings, and a reason that says which absence this is."""

    unavailable: TunerUnavailable
    _reason: str

    @property
    def available(self) -> bool:
        return False

    @property
    def reason(self) -> str:
        return self._reason

    def reading(self) -> TunerReading | None:
        return None

    def amenities(self) -> tuple[CityAmenities, ...]:
        return ()

    def maintenance(self) -> Maintenance | None:
        return None

    def build_options(self) -> tuple[SettlementOptions, ...]:
        return ()


TUNER_OFF = NullTuner(
    TunerUnavailable.NOT_ENABLED,
    "Civilization VI reports amenities, upkeep and build options only through its "
    "tuner socket, which is off. Set `EnableTuner 1` under [Debug] in the game's "
    "AppOptions.txt and restart the game. The advisor never edits that file.",
)


TUNER_ABSENT = NullTuner(
    TunerUnavailable.NO_SOCKET,
    "This game has no tuner socket. These figures have no source here, and there is "
    "nothing you could enable that would add one.",
)


@dataclass(frozen=True)
class TunerSnapshot:
    """What the tuner said during ONE rebuild, frozen and dated to that turn.

    Holding a live provider on a snapshot would let a request read figures from a
    later turn and file them under this one. These values were all read at the same
    moment as the logs beside them.
    """

    available: bool
    reason: str | None = None
    amenities: tuple[CityAmenities, ...] = ()
    maintenance: Maintenance | None = None
    build_options: tuple[SettlementOptions, ...] = ()
    # Why a particular figure is missing, keyed by catalog id. A figure absent from
    # this map was read successfully; one present here says which of the four
    # absences applied to IT, which is not always the same for every figure.
    absences: tuple[tuple[str, str], ...] = ()
    # The reading that dates each figure, keyed by the same catalog id. One reading
    # PER QUERY, deliberately, and no single reading for the capture: each query asks
    # the live game for its own turn, so three replies mean three turns and three
    # instants. A player who presses Enter mid-capture leaves amenities stamped turn
    # 59 and build options stamped 60 -- which is true, and which a shared stamp would
    # silently make false for one of them.
    readings: tuple[tuple[str, TunerReading], ...] = ()
    # WHICH absence this is, beside the prose reason. The provider computes this on
    # eight different paths and `capture` used to drop it, leaving every consumer with
    # nothing but a sentence to guess from -- so a game with no socket at all read
    # identically to a game whose socket is switched off, and only the second is
    # something a player can act on.
    unavailable: TunerUnavailable | None = None

    def absence(self, query_id: str) -> str | None:
        return next((why for q, why in self.absences if q == query_id), None)

    def reading_for(self, query_id: str) -> TunerReading | None:
        """The reading that dates THIS figure, or None if it was never read."""
        return next((r for q, r in self.readings if q == query_id), None)


TUNER_SNAPSHOT_OFF = TunerSnapshot(available=False, reason=TUNER_OFF.reason,
                                   unavailable=TUNER_OFF.unavailable)


def _ask(provider: TunerProvider, query_id: str, fn: Callable[[], object], empty: object):
    """Call one figure, and pair it with the reason AND reading belonging to THAT call.

    Guarded so a provider that raises on one figure cannot lose the other two, and
    both the reason and the reading are read immediately after this call -- before
    anything else on the provider has a chance to clear or replace them for the next
    figure. The reading is what dates this figure, so taking it at any other moment
    would be taking another query's turn.
    """
    try:
        result = fn()
    except Exception as exc:      # a provider's own failures are many shapes; never propagate
        return empty, f"reading {query_id} raised {exc!r}", None
    try:
        reading = provider.reading()
    except Exception:
        reading = None
    if not result:
        reason = getattr(provider, "reason", None)
        if reason:
            return result, reason, reading
    return result, None, reading


def capture(provider: TunerProvider) -> TunerSnapshot:
    """Read every figure once, recording per-figure absence with its real cause.

    One unreachable figure must not discard the two that worked, and must not be
    reported as the reason the others are missing. Never raises: a tuner failure
    must not cost the rebuild that is capturing it.
    """
    if not getattr(provider, "available", False):
        return TunerSnapshot(available=False, reason=getattr(provider, "reason", None),
                             unavailable=getattr(provider, "unavailable", None))

    amenities, amenities_why, amenities_read = _ask(
        provider, "amenities", provider.amenities, ())
    maintenance, maintenance_why, maintenance_read = _ask(
        provider, "maintenance", provider.maintenance, None)
    build_options, build_options_why, build_options_read = _ask(
        provider, "build_options", provider.build_options, ())

    absences = tuple(
        (query_id, why)
        for query_id, why in (
            ("amenities", amenities_why),
            ("maintenance", maintenance_why),
            ("build_options", build_options_why),
        )
        if why
    )
    readings = tuple(
        (query_id, reading)
        for query_id, reading in (
            ("amenities", amenities_read),
            ("maintenance", maintenance_read),
            ("build_options", build_options_read),
        )
        if reading is not None
    )
    return TunerSnapshot(
        available=True,
        reason=None,
        amenities=tuple(amenities),
        maintenance=maintenance,
        build_options=tuple(build_options),
        absences=absences,
        readings=readings,
    )


__all__ = ["BuildOption", "CityAmenities", "Maintenance", "NullTuner",
           "SettlementOptions", "TUNER_ABSENT", "TUNER_OFF", "TUNER_SNAPSHOT_OFF",
           "TunerProvider", "TunerReading", "TunerSnapshot", "TunerUnavailable",
           "capture"]
