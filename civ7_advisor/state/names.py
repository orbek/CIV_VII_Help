"""Resolve the leader names some logs use (Gossip) to player ids.

Rivals are known from AI_Victories owner keys. The human never appears there, but their
civilization does appear in their own city keys (LOC_CITY_NAME_MAURYA1 -> "maurya"), so a
gossip row whose Civilization matches is the human. Anything else stays unresolved — an id
is never guessed.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

HUMAN = 0
_CITY_KEY = re.compile(r"^LOC_CITY_NAME_([A-Z_]+?)\d*$")


@dataclass(frozen=True)
class NameResolver:
    by_leader: dict[str, int]    # normalized display name -> player id
    human_civ: str | None        # normalized civilization name of player 0

    @staticmethod
    def normalize(s: str) -> str:
        decomposed = unicodedata.normalize("NFKD", s)
        stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
        return " ".join(stripped.casefold().split())

    @classmethod
    def build(cls, rival_names: dict[int, str], human_city_keys: list[str]) -> "NameResolver":
        by_leader = {cls.normalize(name): pid for pid, name in rival_names.items()}
        prefixes = Counter()
        for key in human_city_keys:
            m = _CITY_KEY.match(key)
            if m:
                prefixes[cls.normalize(m.group(1).replace("_", " "))] += 1
        human_civ = prefixes.most_common(1)[0][0] if prefixes else None
        return cls(by_leader=by_leader, human_civ=human_civ)

    def player_for(self, leader: str, civilization: str | None = None) -> int | None:
        pid = self.by_leader.get(self.normalize(leader))
        if pid is not None:
            return pid
        if civilization is not None and self.human_civ is not None:
            if self.normalize(civilization) == self.human_civ:
                return HUMAN
        return None
