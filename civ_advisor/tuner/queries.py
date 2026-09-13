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

# Every body below is wrapped in its own pcall. An uncaught error in a Lua
# chunk aborts the whole chunk, so a call that does not exist in this VM would
# otherwise silence the sentinel this module's caller appends after the query
# -- and a caller waiting for a sentinel that will never come cannot tell that
# apart from a game that simply is not running. Printing "PROBEERR" instead
# turns that silence into a line the client can recognise immediately.
_MAINTENANCE_LUA = (
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

__all__ = ["CATALOG", "NOT_IMPLEMENTED", "Query", "looks_unreachable"]
