# Civ VII v2 live-log facts

Captured from the preserved turn-100 session on 2026-09-07. Command output is recorded verbatim except that
blank trailing values are rendered as `<empty>`; conclusions immediately below each block are the reader
decisions pinned by `tests/test_fixture_v2.py`.

## Turn range

```text
1
100
```

Settles: this fixture spans turns 1–100 without a game-segment reset.

## Human civ (player 0 city keys)

```text
LOC_CITY_NAME_AMERICA1
```

Settles: the human civilization is America and city-key name resolution must map America gossip to player 0.

## Gossip column-count distribution

```text
 354 10
 190 11
  60 12
  15 13
   1 14
 529 7
 846 8
 708 9
```

Settles: gossip is unquoted and ragged from 7–14 values. Commas occur in leader names such as
`Napoleon, Revolutionary` and in detail text. The reader anchors on the unique `GOSSIP_*` token, takes the
civilization and plot coordinates from the three cells before it, and joins the leader/detail spans.

## Gossip types

```text
 400 GOSSIP_COMPLETED_PROGRESSION_TREE_NODE
 246 GOSSIP_CONSTRUCT_BUILDING
 230 GOSSIP_CITY_POPULATION_HEIGHT_CHANGED
 214 GOSSIP_FIND_RIVER
 187 GOSSIP_TRAIN_UNIT
 141 GOSSIP_UNIT_COMBAT_DEATH
 125 GOSSIP_UNIT_DESTROYED
 116 GOSSIP_MEET_INDEPENDENT
 113 GOSSIP_DIPLOMACY_ACTION_STARTED
 101 GOSSIP_INDEPENDENT_INFLUENCE
  86 GOSSIP_RELATIONSHIP_CHANGED
  78 GOSSIP_DIPLOMACY_RESPONSE
  77 GOSSIP_TRADITION_ACTIVATED
  71 GOSSIP_POLICY_SLOTS_CHANGED
  67 GOSSIP_GATHER_RESOURCE
  57 GOSSIP_FIND_VOLCANO
  38 GOSSIP_TRIGGER_DISCOVERY
  33 GOSSIP_FOUND_CITY
  32 GOSSIP_MAKE_DOW
  31 GOSSIP_INDEPENDENT_ASSAULT
  30 GOSSIP_TRADITION_DEACTIVATED
  26 GOSSIP_RANDOM_EVENT_DAMAGE
  24 GOSSIP_PILLAGE
  19 GOSSIP_CONSTRUCTIBLE_REPAIRED
  17 GOSSIP_SPEND_ATTRIBUTE
  16 GOSSIP_RELIC_RECEIVED
  16 GOSSIP_GOLDEN_AGE
  13 GOSSIP_PLAYERS_MEET
  11 GOSSIP_UNIT_PROMOTION
  10 GOSSIP_FIND_NATURAL_WONDER
  10 GOSSIP_FIND_CONTINENT
   9 GOSSIP_TRADE_ROUTE_STARTED
   8 GOSSIP_WONDER_STARTED
   8 GOSSIP_CREATE_PANTHEON
   8 GOSSIP_CHANGE_GOVERNMENT
   8 GOSSIP_BECOME_SUZERAIN
   6 GOSSIP_RANDOM_EVENT_DAMAGED_CONSTRUCTIBLE
   3 GOSSIP_LOST_WONDER_RACE
   3 GOSSIP_ALLIED
   2 GOSSIP_URBAN_CONTROL_CHANGED
   2 GOSSIP_RANDOM_EVENT_UNIT_KILLED
   2 GOSSIP_MAKE_PEACE
   2 GOSSIP_CONQUER_CITY
   2 GOSSIP_CITY_RAZED
   2 GOSSIP_ARMY_FILLED
   1 GOSSIP_REJECT_DEAL
   1 GOSSIP_PLAYER_DEFEATED_INDEPENDENT_RAID
   1 GOSSIP_PLACED_WORKER
```

Settles: all 2,703 rows contain a real `GOSSIP_*` type; there is no `-1` type vocabulary.

## DiplomacySummary column-count distribution and trailing-cell values

```text
1171 6
```

The 20 most common trailing values are:

```text
 337 6: 0.0
  40 6: 5.0
  31 6: 13.0
  22 6: 2.5
  18 6: 49.0
  16 6: 1.0
  15 6: 43.0
  13 6: 9.0
  13 6: 292.0
  13 6: 278.5
  13 6: 15.5
  12 6: 85.0
  12 6: 31.5
  11 6: 9.5
  11 6: 78.0
  11 6: 30.5
  11 6: 1.5
  10 6: 71.5
  10 6: 6.5
  10 6: 39.0
```

Settles: every row has six values and the sixth is numeric Mayhem; the seventh header, Visibility, is absent.
The model remains `extra == (mayhem,)` until a bounded rename.

## CombatLog value sets

SourceType:

```text
 329 Unit Heal
   1 Unit vs Army
  55 Unit vs Location
 423 Unit vs Unit
```

CombatType:

```text
 343 <empty>
 307 Melee
 158 Ranged
```

Destroyed:

```text
  27 Attacker
 119 Defender
   4 District
 658 N/A
```

Settles: heal rows have no CombatType; `Destroyed` has Attacker, Defender, District and N/A. Empty synthetic
cells remain supported. Only Attacker and Defender identify a lost unit.

## CombatLog health cells for destroyed combatants (to infer (a)b order)

```text
att (0)100 dmg 69 15
att (0)100 dmg 41 18
att (0)100 dmg 40 19
att (0)100 dmg 45 18
att (0)100 dmg 30 31
def (0)100 dmg 0 66
def (0)100 dmg 0 58
def (0)100 dmg 0 47
def (0)100 dmg 22 47
def (0)100 dmg 26 36
```

Settles: a destroyed combatant's cell is `(0)100`, so health is `(after)before`. Damage columns track damage
taken by the correspondingly named side. Phase 1a still does not quote damage numbers.

## Deal kinds

```text
  16 type <empty>
   8 type Influence Small Lump (40)
   8 type Peace
```

Settles: actual item kinds are Peace and Influence Small Lump (40); the empty matches are the separate
`value type ,` phrase, not an empty item kind. Block headers are Incoming, Enacting and Removing; their turns
are monotonic (84, 86, 99). The current reader deliberately consumes Incoming only; Enacting is a phase-1b
follow-up because it is the acceptance signal.

## CityBuildQueue idle vocabulary

```text
   1 []
```

Settles: an idle city logs an empty Current Item cell, represented by `""` in `BuildQueueRow`.

## GameCore player identity format

```text
[2026-09-07 17:13:59]\tPlayer 0: Civilization - CIVILIZATION_AMERICA (-1651108180)  Leader - LEADER_BENJAMIN_FRANKLIN (-393488514), - Level - CIVILIZATION_LEVEL_FULL_CIV, SlotStatus - Human
```

Settles: GameCore logs an exact player/civilization/leader map. It first logs RANDOM placeholders and later
resolved values, so a future reader must take the last resolved block per player.

## Follow-ups

- This one-Age fixture cannot settle whether human city-key prefixes change across an Age transition or whether
  gossip's Civilization field always follows the current Age civilization.
- Rename DiplomacySummary `extra` to a Mayhem field in a bounded task.
- Read Enacting deal blocks as acceptance and use GameCore identity lines for exact player-name resolution in
  phase 1b.
