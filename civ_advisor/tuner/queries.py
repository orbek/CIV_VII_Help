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

_MAINTENANCE_LUA = (
    'local t=Players[Game.GetLocalPlayer()]:GetTreasury() '
    'print("total", t:GetTotalMaintenance()) '
    'print("buildings", t:GetBuildingMaintenance()) '
    'print("districts", t:GetDistrictMaintenance()) '
    'print("units", t:GetUnitMaintenance()) '
    'print("gold", t:GetGoldBalance()) '
    'print("goldYield", t:GetGoldYield())'
)

_AMENITIES_LUA = (
    'for _,c in Players[Game.GetLocalPlayer()]:GetCities():Members() do '
    'local g=c:GetGrowth() '
    'print(Locale.Lookup(c:GetName()), g:GetAmenities(), g:GetAmenitiesFromLuxuries(), '
    'g:GetAmenitiesFromCivics(), g:GetAmenitiesFromEntertainment(), g:GetHousing(), '
    'g:GetFoodSurplus()) end'
)

# Runs in the UI VM: CanProduce and GetTurnsLeft are present in GameCore_Tuner
# and raise "Not Implemented." there.
_BUILD_OPTIONS_LUA = (
    'for _,c in Players[Game.GetLocalPlayer()]:GetCities():Members() do '
    'local q=c:GetBuildQueue() '
    'for row in GameInfo.Buildings() do '
    'local ok,can=pcall(function() return q:CanProduce(row.Hash,true) end) '
    'if ok and can then print(Locale.Lookup(c:GetName()), row.BuildingType, '
    'q:GetTurnsLeft(row.Hash)) end end end'
)


def looks_unreachable(lines: list[str]) -> bool:
    """Whether a reply says the figure does not exist, rather than carrying one."""
    joined = "\n".join(lines)
    return NOT_IMPLEMENTED in joined or "\tnil" in joined or joined.strip().endswith("nil")


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
