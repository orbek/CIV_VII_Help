# What the game's logs can and cannot tell us

**Game:** Civilization VII. Civilization VI has a different log set and a
different set of things it cannot know; see
[the multi-game design](../superpowers/specs/2026-09-12-multi-game-advisor-design.md)
§3, and this document gains a Civ VI column in phase 2.

Audited 2026-09-08 against `tests/fixtures/logs_v2` (a real session, turns 1–100) and
`tests/fixtures/logs_82turns`. This is the reference for what may be asserted in a
recommendation. A field marked **unknown** has no parser and must not acquire one until
real sample rows support a contract: an empty file is not a data source, and the absence
of a record is not evidence that the thing it would record is absent.

## Available

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

## Unknown — no source found, no parser added

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

## Consequences for the decision layer

1. **No numeric effect for any build item is available from any source we ship.** The guide
   catalog carries none, and the logs carry none. Every figure in a comparison has to come
   from the player's own dated preview, which is why the culture pilot's refinement panel
   is part of the first release rather than an enhancement.
2. **Availability is always unknown.** A named building can only ever be a conditional
   candidate until the player confirms it is offered.
3. **Settlement coverage must be stated.** With one queue row out of six settlements, any
   advice about "your cities" is about the observed one.
4. **The Age is dated, not current.** Anything Age-gated stays conditional.
