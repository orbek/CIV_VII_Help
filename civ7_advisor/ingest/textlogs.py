"""Parsers for the Civ VII logs that are not CSV. Phase 1a: DiplomacyDeals.log."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .csvfile import LogFormatError

_BLOCK = re.compile(r"^Turn (\d+), Incoming for player (\d+) and (\d+)")
_ITEM = re.compile(
    r"^, Item ID (\d+), from player (\d+), to player (\d+), type ([^,]+), subType [^,]*, "
    r"value type [^,]*, amount (-?\d+), duration (-?\d+)"
)
# Any block header at all. "Incoming" is direct evidence that a complementary kind exists —
# "Outgoing", at least — but that vocabulary is INFERRED, not observed: no non-Incoming header
# has been captured live. Task 11's FACTS.md must confirm the real set of block kinds.
# Until then a header we do not recognise ends the current block rather than continuing it, so
# its items are dropped instead of being stamped with the previous block's turn. An outgoing
# `Peace` is an offer, not a concluded peace; reading one as concluded would clear a live war.
_ANY_BLOCK = re.compile(r"^Turn \d+,")


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

    def involves(self, player: int) -> bool:
        return player in self.parties()


def read_deals(path: Path) -> list[DealItem]:
    """Items grouped under `Turn N, Incoming …` headers. Unknown lines are skipped; a header
    whose turn is lower than the previous one means a new game, and earlier items are dropped."""
    out: list[DealItem] = []
    blocks = 0                       # `Incoming` headers parsed in the current game
    turn: int | None = None          # block currently being read; None outside an `Incoming` one
    last_block_turn: int | None = None  # kept separately so an unrecognised header, which clears
                                        # `turn`, cannot disable new-game detection
    with path.open(encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            block = _BLOCK.match(line)
            if block:
                new_turn = int(block.group(1))
                if last_block_turn is not None and new_turn < last_block_turn:
                    out.clear()
                    blocks = 0
                turn = last_block_turn = new_turn
                blocks += 1
                continue
            if _ANY_BLOCK.match(line):
                turn = None
                continue
            item = _ITEM.match(line)
            if item and turn is not None:
                out.append(DealItem(turn, int(item.group(1)), int(item.group(2)), int(item.group(3)),
                                    item.group(4).strip(), int(item.group(5)), int(item.group(6))))
    # Emptiness alone is not evidence of drift: a deal-free early game is legitimately empty,
    # and the file carries unrelated chatter. Headers with no items under them are — the item
    # line was renamed or reordered. Silence here would read downstream as a peaceful game.
    if blocks and not out:
        raise LogFormatError(f"{path.name}: {blocks} deal block(s) but no item line parsed")
    return out
