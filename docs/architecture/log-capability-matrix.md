# What the game's logs can and cannot tell us

This document's body (below) was audited against Civilization VII's logs. Everything
in it applies to Civilization VII only, unless the Civ VI section immediately below
says otherwise.

## Civilization VI

Civ VI has a different log set than Civ VII and cannot support everything the advisor
models. What it declares is enforced by `CIV6.capabilities`
(`civ_advisor/games/civ6/__init__.py`) and checked against its reader table by
`tests/test_profile_conformance.py`, not left to review.

**Unavailable, and why:**

| Capability | Why Civ VI cannot support it |
| --- | --- |
| Victory paths | `AI_Victories.csv` exists, but its rows record era-strategy postures (e.g. `STRATEGY_DARKAGE`), not victory-path pursuit. Populating `GameState.strategies` from it would misreport an era posture as a victory strategy, so Civ VI declares no reader for this file at all. |
| Happiness / amenities | No log records amenities or an empire happiness total; there is no `Player_Happiness.csv` equivalent. |
| Maintenance / net gold | No log records unit, building or total maintenance; there is no `Player_Treasury.csv` equivalent. |
| Peace deals | No log records diplomatic deals; there is no `DiplomacyDeals.log` equivalent. |
| Combat odds | No log records pre-combat odds estimates. |
| Settlement cap / urban-rural split | Civ VI has no settlement-cap or urban/rural-population concept in its stats log; `Player_Stats.csv`'s columns carry no such fields (see `civ_advisor/games/civ6/columns.py`). |
| Tourism / diplomatic favor | Not currently declared. Civ VI's `Player_Stats_2.csv` is expected to carry these (see the multi-game design spec §3.2), but no reader for that file exists yet — declaring the capability without a reader behind it would promise a panel this build cannot fill. Add it back only alongside a `Player_Stats_2.csv` reader and the canonical fields it would populate. |

**Available, and new relative to Civ VII's own field set:**

| Capability | Source |
| --- | --- |
| Faith | `Player_Stats.csv` (`StatsRow.faith`, `StatsRow.faith_balance`), read positionally — `Faith` is the header name of two different columns. |
| Civics | `Player_Stats.csv` (`StatsRow.civics`). |
| Installed ruleset figures (cost, prereqs, flat yields) | `Cache/DebugGameplay.sqlite`, plain indexed rows only. Civ VII has nothing to query — no packaged guide asserts a figure verified against an installed ruleset, so every figure there is `your report`, typed in by the player. Conditional effects (a policy card, a government or wonder ability) are not derivable even here; see [ADR-002](adr-002-ruleset-derived-figures.md) for why. |

See [the multi-game design](../superpowers/specs/2026-09-12-multi-game-advisor-design.md)
§3 for the full spec this is drawn from.

## Civilization VI-only signals (phase 3)

All four are AI-internal and every claim built from them is ORACLE. Civ VII
writes none of these files, declares none of these capabilities, and its
advisors see four empty lists.

| File | Capability | What it supports | What it does NOT support |
|---|---|---|---|
| `AI_Military.csv` | `combat_desire` | The AI's own appetite for a fight, per player per turn. Reported as rank within the turn and change over 10 turns. | An absolute danger level. The game publishes no scale, one capture cannot establish one, and the insight never rises above ADVISE. |
| `DiplomacyModifiers.csv` | `diplomatic_modifiers` | Standing negative modifiers between the human and a rival, quoted in the game's own wording. | Which side holds the opinion. The log records the ordered pair but never the direction, and the capture writes one meeting in both orderings. |
| `AI_Research.csv` | `research_preference` | The AI's stated research goal (`Boost == GOAL`) and its top-scored techs, per turn. | Any victory path. See the design §3.2. |
| `AI_GovtPolicies.csv` | `policy_preference` | Top-scored civics and policy cards, per turn. | Any victory path; also no `GOAL` marker exists in this file at all. |

## Civilization VII

Audited 2026-09-08 against `tests/fixtures/logs_v2` (a real session, turns 1–100) and
`tests/fixtures/logs_82turns`. This is the reference for what may be asserted in a
recommendation. A field marked **unknown** has no parser and must not acquire one until
real sample rows support a contract: an empty file is not a data source, and the absence
of a record is not evidence that the thing it would record is absent.

### Available

| Field | Source | Contract | Caveat that must travel with it |
| --- | --- | --- | --- |
| Per-turn yields, settlement counts and cap, unit counts, tiles, techs — for every major | `Player_Stats.csv` | `GameState.at(player, turn)` | Empire-wide. A total never establishes one settlement's local capacity. |
| Gold balance, unit/building/total maintenance | `Player_Treasury.csv` | `PlayerTurn.net_gold` | Optional file. When absent, net income is unknown — a balance alone is not affordability. |
| Happiness total and celebration threshold | `Player_Happiness.csv` | `PlayerTurn.celebration_progress` | Empire-wide; says nothing about a settlement's local happiness room. |
| Current build item, progress, production needed, per-turn production added — per logged settlement | `CityBuildQueue.csv` | `production.queues` | **Not a census.** In the v2 fixture only 1 of the human's 6 settlements has a queue row. Unlogged settlements are unobserved, not idle. |
| Items that appear to have completed | `CityBuildQueue.csv` (derived) | `evidence.completed_item_facts` | Inference: logged production met what was needed and the next turn shows a different item. A hand-changed queue looks the same. Nothing before the log started is visible. |
| Human civilization and leader | `GameCore.log` | `GameState.identities[0]` | Recorded at save load; carries no turn. `RANDOM` placeholder lines are skipped. |
| Age label on world events | `Historian.csv` (`Age` column) | `evidence.age_fact` | Dates the Age; does **not** state the current Age. In the v2 fixture every one of 184 events is `AGE_ANTIQUITY`, turns 3–100. Two Ages on one turn means a transition and the current Age is then unreadable. |
| Rival attack objectives against known city-area tiles | `AI_Operation.csv`, `AI_CombatPlanning.csv`, `AI_Targets.csv` | `tactical.attack_goals` | Oracle. Episodic: re-emitted each turn it is held, so a stale row is a dated last-known objective. No record is not safety. |
| Rival unit sightings, unit-efficiency ratings, operation odds, commander promotions | the `AI_*` logs | `advisors/tactical.py` | Oracle. AI estimates, not win probabilities. |
| Rival diplomatic intent, war score, deals, gossip, combat results | `AI_DiplomaticActions.csv`, `DiplomacySummary.csv`, `DiplomacyDeals.log`, `Game_Gossip.csv`, `CombatLog.csv` | `advisors/threat.py`, `advisors/intel.py` | Mixed provenance; the intent and score rows are Oracle. |

### Unknown — no source found, no parser added

| Field | Why it is unknown | What a recommendation must do instead |
| --- | --- | --- |
| Current Age and ruleset/version | No log states either. `Historian.csv` dates Ages via events only; no file records the game version, DLC or mods. | Treat as unknown: offer conditional guidance or an inspection, or take it as an explicit player setting. Never assert an Age-gated effect. |
| Which items a settlement can currently build | Nothing enumerates available options. `CityBuildQueue.csv` records only what is being built. | Ask the player which options the production list offers, or give the inspection step. Never name a build as available. |
| Unlocks, technologies and civics chosen, policies in force | `Player_Stats.csv` has a `techs` count and nothing else; no file lists them. | Never claim a prerequisite is met. `Prerequisite.UNKNOWN`, never `MET`. |
| Buildings and improvements already present in a settlement | Only inferable from observed completions since the log began — which excludes everything built earlier. | Say the record starts at the session, or ask. Absence is not evidence of absence. |
| Specialist slots, current and maximum, per settlement | No log. The official guide says the game shows this on urban tiles. | Give the in-game inspection step; empire totals cannot validate a specialist decision. |
| Tile adjacency, terrain, resources, legal placements | `AI_Targets.csv` gives plot coordinates for AI targeting only; nothing describes tiles. | Never fabricate coordinates or an expected gain. Ask for the displayed preview values. |
| Per-city yield, maintenance and overbuilding effects | Not logged at settlement level. | Ask for the placement preview, which the publisher documents as showing exactly these. |
| Rival settlement names | Not recorded; only `LOC_CITY_NAME_*` keys for the human's own queues. | Do not invent names. |

### Consequences for the decision layer

1. **No numeric effect for any build item is available from any source we ship.** The guide
   catalog carries none, and the logs carry none. Every figure in a comparison has to come
   from the player's own dated preview, which is why the culture pilot's refinement panel
   is part of the first release rather than an enhancement.
2. **Availability is always unknown.** A named building can only ever be a conditional
   candidate until the player confirms it is offered.
3. **Settlement coverage must be stated.** With one queue row out of six settlements, any
   advice about "your cities" is about the observed one.
4. **The Age is dated, not current.** Anything Age-gated stays conditional.
