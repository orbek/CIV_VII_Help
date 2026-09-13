"""The fixed set of questions the advisor may ask the game.

This module is the allowlist, in the same sense as READABLE_COLUMNS in
ruleset/civ6.py: a question that is not written here cannot be asked. Every
`lua` below is a module constant with no placeholder of any kind, so no value
that came from a player can reach the game as code.

Each entry records the VM it runs in and the date it was verified against a
real game, because a binding that exists in one VM can be a stub in another.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .base import BuildOption, CityAmenities, Maintenance, SettlementOptions

# The game raises this, with a Lua traceback, for a binding that exists but is
# not wired up in that VM. It is a permanent property of the game, not a
# transient failure, so it is read as absence and never retried.
NOT_IMPLEMENTED = "Not Implemented."

# The first line of every reply names the game's OWN current turn. Asked once per
# query rather than once per capture on purpose: a turn read separately could
# advance before the figures it was meant to date, and the logs' own turn is not
# this turn at all -- the logs are complete only through the last finished turn,
# while the socket reads the live game, and the two disagree exactly when the
# player is mid-turn. `Game.GetCurrentGameTurn()` was verified live in
# GameCore_Tuner during the spike, where it answered 59. It is NOT separately
# verified in the InGame VM that build_options uses, which is why it gets its own
# pcall ahead of the body's: if the call is missing there, the figures still print
# and the client reports build_options absent rather than filing real figures under
# a turn nobody named.
TURN_FIELD = "turn"

_TURN_LUA = (
    'local okTurn,errTurn=pcall(function() '
    'print("' + TURN_FIELD + '", Game.GetCurrentGameTurn()) end) '
    'if not okTurn then print("PROBEERR", tostring(errTurn)) end '
)

# Every body below is wrapped in its own pcall. An uncaught error in a Lua
# chunk aborts the whole chunk, so a call that does not exist in this VM would
# otherwise silence the sentinel this module's caller appends after the query
# -- and a caller waiting for a sentinel that will never come cannot tell that
# apart from a game that simply is not running. Printing "PROBEERR" instead
# turns that silence into a line the client can recognise immediately.
_MAINTENANCE_LUA = (
    _TURN_LUA +
    'local ok,err=pcall(function() '
    'local t=Players[Game.GetLocalPlayer()]:GetTreasury() '
    'print("total", t:GetTotalMaintenance()) '
    'print("buildings", t:GetBuildingMaintenance()) '
    'print("districts", t:GetDistrictMaintenance()) '
    'print("units", t:GetUnitMaintenance()) '
    'print("gold", t:GetGoldBalance()) '
    'print("goldYield", t:GetGoldYield()) end) '
    'if not ok then print("PROBEERR", tostring(err)) end'
)

_AMENITIES_LUA = (
    _TURN_LUA +
    'local ok,err=pcall(function() '
    'for _,c in Players[Game.GetLocalPlayer()]:GetCities():Members() do '
    'local g=c:GetGrowth() '
    'print(Locale.Lookup(c:GetName()), g:GetAmenities(), g:GetAmenitiesFromLuxuries(), '
    'g:GetAmenitiesFromCivics(), g:GetAmenitiesFromEntertainment(), g:GetHousing(), '
    'g:GetFoodSurplus()) end end) '
    'if not ok then print("PROBEERR", tostring(err)) end'
)

# Runs in the UI VM: CanProduce and GetTurnsLeft are present in GameCore_Tuner
# and raise "Not Implemented." there. CanProduce already guards itself with an
# inner pcall (its failure is expected for buildings a settlement cannot
# build); the outer pcall added here also covers GetTurnsLeft, which is not
# expected to fail but must not be allowed to abort the whole reply if it does.
_BUILD_OPTIONS_LUA = (
    _TURN_LUA +
    'local ok,err=pcall(function() '
    'for _,c in Players[Game.GetLocalPlayer()]:GetCities():Members() do '
    'local q=c:GetBuildQueue() '
    'for row in GameInfo.Buildings() do '
    'local ok2,can=pcall(function() return q:CanProduce(row.Hash,true) end) '
    'if ok2 and can then print(Locale.Lookup(c:GetName()), row.BuildingType, '
    'q:GetTurnsLeft(row.Hash)) end end end end) '
    'if not ok then print("PROBEERR", tostring(err)) end'
)


def looks_unreachable(lines: list[str]) -> bool:
    """Whether a reply says the figure does not exist, rather than carrying one."""
    joined = "\n".join(lines)
    return (
        NOT_IMPLEMENTED in joined
        or "\tnil" in joined
        or joined.strip().endswith("nil")
        # Observed live: an uncaught Lua error prints a "Runtime Error"/"ERR:"
        # line from the game's own error reporting before the chunk aborts.
        # "PROBEERR" is this module's own pcall guard from above.
        or "Runtime Error" in joined
        or "ERR:" in joined
        or "PROBEERR" in joined
    )


def _fields(line: str) -> list[str]:
    return [p for p in line.split("\t") if p != ""]


def split_turn(lines: list[str]) -> tuple[int | None, list[str]]:
    """The game turn this reply named, and the reply with that line removed.

    `None` means the reply carried no turn, which is not a figure the caller may
    paper over: a value that cannot be dated must be reported absent rather than
    filed under whatever turn happened to be lying around.
    """
    turn: int | None = None
    rest: list[str] = []
    for line in lines:
        parts = _fields(line)
        if turn is None and len(parts) == 2 and parts[0] == TURN_FIELD:
            try:
                turn = int(parts[1])
                continue
            except ValueError:
                pass      # not the turn line after all; keep it for the parser
        rest.append(line)
    return turn, rest


def _parse_maintenance(lines: list[str]) -> Maintenance:
    got: dict[str, int] = {}
    for line in lines:
        parts = _fields(line)
        if len(parts) == 2:
            try:
                got[parts[0]] = int(parts[1])
            except ValueError:
                continue
    needed = ("total", "buildings", "districts", "units", "gold", "goldYield")
    missing = [n for n in needed if n not in got]
    if missing:
        raise ValueError(f"maintenance reply is missing {missing}")
    return Maintenance(total=got["total"], buildings=got["buildings"],
                       districts=got["districts"], units=got["units"],
                       gold=got["gold"], gold_yield=got["goldYield"])


def _parse_amenities(lines: list[str]) -> tuple[CityAmenities, ...]:
    out: list[CityAmenities] = []
    for line in lines:
        parts = _fields(line)
        if len(parts) != 7:
            continue
        city, *rest = parts
        try:
            total, lux, civ, ent, housing, food = (int(v) for v in rest)
        except ValueError:
            continue
        out.append(CityAmenities(city=city, total=total, from_luxuries=lux,
                                 from_civics=civ, from_entertainment=ent,
                                 housing=housing, food_surplus=food))
    if not out:
        raise ValueError("amenities reply named no settlement")
    return tuple(out)


def _parse_build_options(lines: list[str]) -> tuple[SettlementOptions, ...]:
    grouped: dict[str, list[BuildOption]] = {}
    for line in lines:
        parts = _fields(line)
        if len(parts) != 3:
            continue
        city, item, turns = parts
        try:
            grouped.setdefault(city, []).append(BuildOption(item=item, turns=int(turns)))
        except ValueError:
            continue
    return tuple(SettlementOptions(city=c, options=tuple(o)) for c, o in grouped.items())


@dataclass(frozen=True)
class Query:
    """One reviewed question: its Lua, the VM it needs, and how to read the reply."""

    id: str
    state: str
    lua: str
    verified_on: str
    parse: Callable[[list[str]], object]


CATALOG: dict[str, Query] = {
    q.id: q for q in (
        Query("maintenance", "GameCore_Tuner", _MAINTENANCE_LUA, "2026-09-13",
              _parse_maintenance),
        Query("amenities", "GameCore_Tuner", _AMENITIES_LUA, "2026-09-13",
              _parse_amenities),
        Query("build_options", "InGame", _BUILD_OPTIONS_LUA, "2026-09-13",
              _parse_build_options),
    )
}

__all__ = ["CATALOG", "NOT_IMPLEMENTED", "Query", "TURN_FIELD",
           "looks_unreachable", "split_turn"]
