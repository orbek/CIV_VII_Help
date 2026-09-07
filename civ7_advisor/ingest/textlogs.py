"""Parsers for the Civ VII logs that are not CSV. Phase 1a: DiplomacyDeals.log."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_BLOCK = re.compile(r"^Turn (\d+), Incoming for player (\d+) and (\d+)")
_ITEM = re.compile(
    r"^, Item ID (\d+), from player (\d+), to player (\d+), type ([^,]+), subType [^,]*, "
    r"value type [^,]*, amount (-?\d+), duration (-?\d+)"
)


@dataclass(frozen=True)
class DealItem:
    turn: int
    item_id: int
    from_player: int
    to_player: int
    kind: str        # "Peace", "Influence Large Lump (100)", "Open Borders", ...
    amount: int
    duration: int

    @property
    def is_peace(self) -> bool:
        return self.kind == "Peace"

    def parties(self) -> frozenset[int]:
        return frozenset({self.from_player, self.to_player})


def read_deals(path: Path) -> list[DealItem]:
    """Items grouped under `Turn N, Incoming …` headers. Unknown lines are skipped; a header
    whose turn is lower than the previous one means a new game, and earlier items are dropped."""
    out: list[DealItem] = []
    turn: int | None = None
    with path.open(encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            block = _BLOCK.match(line)
            if block:
                new_turn = int(block.group(1))
                if turn is not None and new_turn < turn:
                    out.clear()
                turn = new_turn
                continue
            item = _ITEM.match(line)
            if item and turn is not None:
                out.append(DealItem(turn, int(item.group(1)), int(item.group(2)), int(item.group(3)),
                                    item.group(4).strip(), int(item.group(5)), int(item.group(6))))
    return out
