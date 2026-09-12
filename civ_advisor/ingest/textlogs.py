"""Parsers for Civ VII's block- and line-oriented logs."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .csvfile import LogFormatError

_BLOCK = re.compile(r"^Turn (\d+), Enacting Deal id \d+ for player (\d+) and (\d+)")
_ITEM = re.compile(
    r"^, Enacting Deal Item ID (\d+), from player (\d+), to player (\d+), type ([^,]+), subType [^,]*, "
    r"value type [^,]*, amount (-?\d+), duration (-?\d+)"
)
# Any block header at all. The live fixture contains Incoming, Enacting, and Removing blocks.
# A header we do not recognise ends the current block rather than continuing it, so
# its items are dropped instead of being stamped with the previous block's turn. Incoming
# `Peace` is only a proposal; only Enacting establishes that the deal was accepted.
_ANY_BLOCK = re.compile(r"^Turn (\d+),")
_PLAYER = re.compile(
    r"Player (\d+): Civilization - ([A-Z0-9_]+) \([^)]*\)\s+"
    r"Leader - ([A-Z0-9_]+|\(null\)) \([^)]*\), - Level - ([A-Z0-9_]+), "
    r"SlotStatus - ([A-Za-z]+)"
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

    def involves(self, player: int) -> bool:
        return player in self.parties()


@dataclass(frozen=True)
class PlayerIdentityRow:
    turn: int  # GameCore has no game turn; zero keeps the shared loader status contract.
    player: int
    civilization: str
    leader: str | None
    level: str
    slot_status: str


def read_deals(path: Path) -> list[DealItem]:
    """Items grouped under accepted `Turn N, Enacting Deal …` headers. Unknown lines are skipped; a header
    whose turn is lower than the previous one means a new game, and earlier items are dropped."""
    out: list[DealItem] = []
    blocks = 0                       # `Enacting` headers parsed in the current game
    turn: int | None = None          # block currently being read; None outside an `Enacting` one
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
            other = _ANY_BLOCK.match(line)
            if other:
                new_turn = int(other.group(1))
                if last_block_turn is not None and new_turn < last_block_turn:
                    out.clear()
                    blocks = 0
                last_block_turn = new_turn
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


def read_player_identities(path: Path) -> list[PlayerIdentityRow]:
    """Return the last resolved GameCore identity BLOCK.

    GameCore emits the identity map in discrete blocks, each restarting at a
    "Player 0:" line: first RANDOM placeholders, then the resolved map, and
    (on a reload, or across a Civ VI log that never truncates and so spans
    every game ever played) another complete map appended later. Grouping by
    block and keeping only the LAST block that resolved anything is what
    makes this safe for Civ VI: scanning every line as one running "last line
    per player" map (the previous approach) let a player from an earlier,
    unrelated game survive into the current one whenever that earlier game
    happened to field more players than the current one -- and worse, made a
    civilization that sat at a different id across two games look "fielded
    by two players" to `_player_by_civilization`, silently dropping a live
    rival. Civ VII's own log has exactly one resolved block per launch, or
    two across a reload; grouping changes nothing there, and a file with no
    "Player 0:" line at all degrades to one running block, i.e. the previous
    behaviour.
    """
    blocks: list[dict[int, PlayerIdentityRow]] = []
    current: dict[int, PlayerIdentityRow] | None = None
    with path.open(encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            match = _PLAYER.search(line)
            if not match:
                continue
            player = int(match.group(1))
            if player == 0 or current is None:
                current = {}
                blocks.append(current)
            if match.group(2) == "RANDOM" or match.group(3) == "RANDOM":
                continue
            current[player] = PlayerIdentityRow(
                0, player, match.group(2),
                None if match.group(3) == "(null)" else match.group(3),
                match.group(4), match.group(5),
            )
    resolved_blocks = [b for b in blocks if b]
    latest = resolved_blocks[-1] if resolved_blocks else {}
    return [latest[player] for player in sorted(latest)]
