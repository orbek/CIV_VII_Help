# Multi-Game Advisor — Civilization VI alongside Civilization VII

**Date:** 2026-09-12
**Status:** Designed; not yet planned
**Builds on:** `2026-09-07-civ7-advisor-v2-design.md` (v2, shipped on `main`)
**Delivery:** four phases, **one implementation plan per phase**, each
shippable on its own. Phase 1 is planned first; later phases are planned
only after the previous one has landed and its fixture headers are pinned.

## 1. Purpose

The advisor reads Civilization VII's own logs and gives evidence-backed
per-turn advice. Civilization VI is installed on the same machine and
writes a comparable gameplay log set. This design makes the advisor
**game-aware**: one application, one UI, one advisor layer, serving both
games from per-game ingest adapters.

The product goal is unchanged — **learning**, with every claim carrying its
evidence, and everything drawn from data the game hides labelled ORACLE.
This design extends that discipline across two games: a signal one game
exposes and the other does not must be reported as *unavailable in this
game*, never as a zero or a silence.

The program remains **read-only with respect to both games' directories**.

## 2. What the brainstorm got wrong, and what changes

Two assumptions were falsified by probing a live Civ VI match on
2026-09-12. Each is a binding correction.

| Assumption | Reality | Consequence |
|---|---|---|
| "Civ VI does not emit per-turn state; parity needs a companion mod, the FireTuner socket, or save-file parsing." | **Civ VI writes its gameplay telemetry out of the box.** Observed after three turns from a cold `Logs/` directory: 47 new files, 39 of them CSVs, including `Player_Stats.csv`, `AI_Victories.csv`, `AI_Tactical.csv`, `AI_Operation.csv`, `DiplomacySummary.csv`, `CombatLog.csv`, `City_BuildQueue.csv`. No mod, no `EnableTuner`, no settings change, no achievement loss. | None of the three game-side mechanisms is needed. The file-tailing architecture carries over unchanged. |
| "Civ VI is the inverse of VII: weak telemetry, strong ruleset." | Only the second half holds. VI has **both** — comparable telemetry *and* `Cache/DebugGameplay.sqlite` (18 MB, 318 tables) carrying the installed ruleset. | VI's Oracle layer is *richer* than VII's (§3.3), and the "no verified figures" constraint in the README does not apply to VI (§7). |

## 3. Data sources

All headers below were captured from a live Civ VI match on 2026-09-12
(turn 3, Julius Caesar of Rome, 15 majors plus Free Cities). They are
pinned by `expect_header` exactly as the Civ VII headers are.

Logs directory:
`~/Library/Application Support/Sid Meier's Civilization VI/Firaxis Games/Sid Meier's Civilization VI/Logs`

Player 0 remains the human in both games.

### 3.1 One reader serves both games (6 files)

`DiplomacySummary.csv`, `UnitOperations.log`, `AI_Tactical.csv`,
`AI_Operation.csv`, `AI_MayhemTracker.csv` are byte-identical in header
between the two games.

`AI_UnitEfficiency.csv` joins them: its header is the game's own unit
vocabulary and so differs, but the existing reader pins only *shape* — an
empty first cell and a square, non-ragged matrix. VI's matrix is 133×133
and parses unchanged.

All six move to a shared reader module; neither game gets a copy.

### 3.2 Same concept, different columns — VI variant reader (5 files)

| File | Difference |
|---|---|
| `Player_Stats.csv` | VI: `Game Turn, Player, Num Cities, Population, Techs, Civics, Land Units, corps, Armies, Naval Units, TILES: Owned, Improved, BALANCE: Gold, Faith, YIELDS: Science, Culture, Gold, Faith, Production, Food`. Keys rows by **civilization string**, not player id (§5). No towns, settlement cap, urban/rural split, happiness or diplomacy yield. Adds civics, faith, corps, armies. |
| `AI_Victories.csv` | VI: `Game Turn, Player, Strategy, Status` — no `Owner`, no `Percentage`, **no weight column**. `StrategyStatus.weight` is therefore unavailable in VI and must be declared so, not defaulted to 0. |
| `CombatLog.csv` | VI: `Game Turn, Attacking Civ, DefendingCiv, AttackerObjType, DefenderObjType, Attacker Type, Defender Type, AttackerID, DefenderID, AttackerStr, DefenderStr, AttackerStrMod, DefenderStrMod, AttackerDmg, DefenderDmg`. No `Location`, `Destroyed`, `HealAmount`, `attHealth`, `defHealth`. |
| `AI_Operation_Eval.csv` | VI: `Game Turn, Player, Enemy, Operation Name, Value` — **no `Odds` column**. The AI's own odds, which v2 §3.6 made the basis of bounded combat prediction, do not exist in VI. Combat prediction is unavailable in VI and says so. |
| `GameCore.log` | Different identity line shapes (§5). |

`CityBuildQueue.csv` is named `City_BuildQueue.csv` in VI and **drops the
`Player` column** while still logging every city in the game — the observed
match had 15 cities across the human, rivals and city-states in one
undifferentiated stream. Ownership is therefore not in the file. It is
recovered by joining city name against `AI_CityBuild.csv`, whose
`Game Turn, Player, City, ...` rows give city → player for every city each
turn. Two consequences the reader must handle: the join is per-turn, so a
city captured mid-game changes owner correctly; and `AI_CityBuild`'s City
column sometimes carries the sentinel `PURCHASE` instead of a city name,
which must be discarded rather than treated as a city. A queue row whose
city has no owner in that turn's join is attributed to no player and
reported as such, not defaulted to the human.

### 3.3 VI-only, and worth reading (Tier 1)

| File | Header | Why |
|---|---|---|
| `AI_Military.csv` | `Game Turn, Player, Regional Strength, Enemy Strength, Other Strength, Current Explorers, Desired Explorers, Fav Tech, Combat Desire` | An explicit per-player, per-turn **combat desire** and enemy-strength reading. A more direct war-intent signal than anything VII exposes. ORACLE. |
| `AI_Research.csv` | `Game Turn, Player, Action, Tech, Score, Boost, Turns` | The AI's *scored* tech preferences each turn. ORACLE. |
| `AI_GovtPolicies.csv` | `Game Turn, Player, Action, Policy, Score, Turns` | The same for civics and policies. ORACLE. |
| `DynamicEmpires.csv` | `Turn,Era,Player,DarkAge,GoldenAge, Commemoration(s),TotalScore,...` | Supplies the golden-age flag VII reads from `Player_Happiness.csv`. |
| `Game_PlayerScores.csv` | `Game Turn, Player, Score, CATEGORY_*` | Numeric player ids; substitutes for VII's `Historian.csv` as the broad-standing series. |
| `Player_Stats_2.csv` | `Game Turn, Player, BY TYPE: Tiles, Buildings, Districts, Population, Outgoing Trade Routes, TOURISM, Diplo Victory, BALANCE: Favor, LIFETIME: Favor, CO2 Per Turn` | Buildings/districts counts, tourism, favor. Also civ-string keyed. |
| `DiplomacyModifiers.csv` | `Game Turn, Player, Opponent, Modifier, Change, Value, Max, Accum Amt, Accum Turns, Cooldown Turns, Reduction` | Per-pair diplomatic grievance accounting. ORACLE. |
| `Game_Boosts.csv` | `Game Turn, Player, Boosted System, Progress` | Eureka/inspiration state. |

### 3.4 VI-only, parse only when an insight needs them (Tier 2)

`AI_Governors.csv`, `AI_Espionage.csv`, `AI_Religious.csv`,
`AI_Planning.csv`, `AI_Knowledge.csv`, `AI_CityBuild.csv`,
`Game_GreatPeople.csv`, `Game_Influence.csv`, `World_Congress.csv`,
`Game_Emergencies.csv`, `Barbarians.csv`, `Barbarians_Units.csv`,
`AI_ChokePoint.csv`.

### 3.5 Absent in VI, with what replaces them

| VII file | VI substitute |
|---|---|
| `Player_Treasury.csv` | Gold balance is in `Player_Stats` (`BALANCE: Gold`). **Maintenance breakdown has no substitute** — unit/building/total maintenance and therefore `net_gold` are unavailable in VI. |
| `Player_Happiness.csv` | Golden age from `DynamicEmpires.csv`. **Amenities have no substitute**; VI's happiness fields are unavailable. |
| `AI_DiplomaticActions.csv` | `AI_Diplomacy.csv` (a wide per-player diplomatic-state matrix) plus `DiplomacyManager.csv`. Different shape; a VI-specific reader producing the same `DiplomaticIntent` rows. |
| `Historian.csv` | `Game_PlayerScores.csv`. |
| `Game_Gossip.csv` | `DiplomacyManager.csv` (partial — typed messages, not prose gossip). |
| `AI_Targets.csv` | `AI_Planning.csv` (partial). |
| `DiplomacyDeals.log` | **No substitute.** Peace detection — and therefore the v2 fix for "war CRITICAL persists after a treaty" — is unavailable in VI. This is a real regression in VI and must be stated in the capability matrix, not worked around. |
| `AI_CombatPlanning.csv` | **No substitute.** |
| `AI_Commander_Promotions.csv` | Not applicable; VI has no commander units. |

### 3.6 Rejected, with reasons

- `AI_Behavior_Trees.csv` (2.7 MB after three turns) and `AI_ChokePoint.csv`
  (1.1 MB): growth rate makes them unsuitable for a one-second poll loop,
  and nothing currently needs them.
- `RandCalls.csv`, `AStar_*.log`, `SynthesisLog.log`, `DynGeoLog.log`,
  `VFXSystem.log`, `net_*`: engine noise.
- Save-file parsing and the FireTuner socket: unnecessary (§2), and both
  carry risk the log files do not.

## 4. Architecture

```
civ_advisor/
  games/
    __init__.py        GameProfile, registry, auto-detection
    civ7/              reader table, expected headers, identity, guides
    civ6/              reader table, expected headers, identity, guides
  ingest/              csvfile, poller, shared readers (§3.1), load(dir, profile)
  state/               canonical models, build(raw, profile)
  advisors/            game-agnostic
  decisions/           game-agnostic
  knowledge/
    civ7/guides.json
    civ6/guides.json
  api/ web/ llm/ store  unchanged
```

A `GameProfile` carries: id (`civ6` | `civ7`), display name, default logs
directory, the reader table, the capability declaration (§6), the
knowledge catalog path, and the identity strategy.

`load_logs(logs_dir, profile)` takes its reader table from the profile
rather than a module constant. `build_state(raw, profile)` likewise.
Everything downstream of `build_state` is untouched.

The package is renamed `civ7_advisor` → `civ_advisor`. The `civ7-advisor`
console script is retained as an alias for `civ-advisor` so existing
commands and the README keep working.

## 5. Player identity in Civ VI

VI's `Player_Stats.csv` and `Player_Stats_2.csv` key rows by civilization
string (`CIVILIZATION_ROME`); every other VI log uses numeric player ids.
The join is built from three `GameCore.log` line shapes:

```
Player 0: Civilization - (null) (0)  Leader - (null) (-1), - Level - CIVILIZATION_LEVEL_FULL_CIV, SlotStatus - Human
Player 0 is now using leader LEADER_JULIUS_CAESAR.
Civilization already used: Player 0 - CIVILIZATION_ROME
```

The first gives slot, level and human/AI. The second gives the leader. The
third gives the civilization — but it is emitted only while resolving
*later* players, so **the last-resolved player's civilization never
appears**. That one is recovered by elimination against the civilization
set in `Player_Stats`. If elimination is ambiguous — two unresolved
players, or a non-random draft that emits no resolution lines at all — the
player is reported as unnamed rather than guessed. A wrong leader
attribution would misattribute every piece of advice about that rival.

City-states (`CIVILIZATION_GENEVA`, `CIVILIZATION_HATTUSA`, …) and
`CIVILIZATION_FREE_CITIES` classify as `PlayerKind.INDEPENDENT`; the
observed match had majors at ids 0–14 and Free Cities at 63.

## 6. The canonical state, and the guard on it

Normalising two games into one `GameState` risks the model quietly
becoming "Civ VII's model with extra fields". Two rules prevent that.

**Every game-specific field is `T | None`.** `PlayerTurn` gains VI's
`civics`, `faith`, `tourism`, `favor`, `buildings`, `districts`, `corps`,
`armies`; VII's `towns`, `settlement_cap`, `settlements_over_cap`,
`urban_pop`, `rural_pop`, `happiness`, `diplomacy`, and the maintenance
fields become optional. `StrategyStatus.weight` becomes optional.

**Absence is declared, never inferred.** Each profile declares which
canonical fields and which advisor capabilities it supports. An advisor
asking for a field the current game does not have gets *unavailable*
through the existing `FileStatus` / capability-matrix path that the header
already renders — never `0.0`, which would read as "this civ is miserable"
rather than "this game has no such concept". The declaration is the source
of truth; a `None` arriving from a field the profile claims to support is a
parse failure and is reported as one.

Consequence: every advisor must be audited for `None` handling as part of
phase 2, not after it. `GameState.series()` already skips `None`, which is
correct for optional fields but means a caller cannot distinguish "short
series" from "unsupported"; callers that care must consult the capability
declaration.

## 7. Knowledge and figures — where the games genuinely diverge

`guides.json` splits per game; the existing catalog becomes
`knowledge/civ7/guides.json` and the link checker gains a `--game` flag.

Separately: VI ships `Cache/DebugGameplay.sqlite`, containing the installed
ruleset (`Buildings`, `Building_YieldChanges`, `Districts`, `Technologies`,
`Civics`, `Policies`, `Governments`, `Units` among 318 tables). The
README's constraint — that no figure in a recommendation may come from a
wiki or from the advisor's own guesses, because nothing can be verified
against an installed ruleset — **does not apply to Civ VI**. A ruleset
provider can answer "what does this building yield, what does it cost"
from the game's own data.

This is a real capability divergence, not a parity gap, and it changes the
"Refine this recommendation" flow for VI: figures can be looked up rather
than typed in. It is scoped to phase 4 so that parity work is not delayed
by it, and so the provenance labelling ("installed ruleset" as a source
class distinct from "your report") gets its own design attention.

## 8. Storage and selection

- `--game civ6 | civ7 | auto`. `auto` selects whichever game's logs
  directory holds the most recently modified *gameplay* log, and says
  which it chose. Ambiguity resolves to an error naming both, not a guess.
- `--logs-dir` continues to override, and implies `--game` must be explicit.
- The archive root and the player-context store namespace per game:
  `~/.civ-advisor/<game>/`. Acknowledgements, pins, goals and watchlist
  entries must not cross games. The existing sitting/reload logic is
  unchanged within a game.
- The header reports which game is being advised and from which directory.

VII deletes its `Logs/` directory on every launch (v2 §2), which is why
`archive.py` exists. **VI does not** — its logs are append-only across
games and sessions. `latest_game_segment` already handles the resulting
turn-column sawtooth. Archiving is retained for VI but matters less; it
still serves phase-3 calibration.

## 9. Error handling

Per-file isolation (v2 §6.1) is unchanged and now does more work: VI and
VII differ in which files exist at all, so a missing file must be
distinguishable from a file this game never had. `FileStatus` gains a
`declared` notion — a file the profile does not declare is absent by
design and is not reported as a fault.

Header pinning is brittle across game patches, and this design doubles the
surface. Accepted: a pinned header that stops matching fails loudly with
the observed and expected headers side by side, which is the existing and
correct behaviour.

## 10. Testing

- The 36 existing test files must stay green against the `civ7` profile
  after the rename. Phase 1 changes no behaviour; a green suite is the
  acceptance criterion.
- VI readers get golden fixtures captured from the 2026-09-12 match.
- A **profile conformance test**: for every game, every declared reader's
  expected header matches its captured fixture, and every capability the
  profile declares has a field or advisor backing it. This is what stops
  the capability declaration and the code drifting apart.
- A **cross-game advisor test**: each advisor runs against a state built
  from each profile, asserting that unsupported signals surface as
  unavailable rather than as zeros.

## 11. Phases

1. **Neutral core.** Rename to `civ_advisor`, introduce `GameProfile` and
   the registry, move Civ VII's readers and headers behind the `civ7`
   profile. **Zero behaviour change**; the existing suite is the proof.
2. **Civ VI profile.** Readers (§3.1–3.2, §3.5), identity (§5), canonical
   state and the capability guard (§6), selection and namespaced storage
   (§8), fixtures and conformance tests (§10). Parity on the overlapping
   signals; the capability matrix honest about amenities, maintenance,
   deals, combat odds.
3. **VI-only signals into existing advisors.** Combat desire and
   diplomatic modifiers into the threat advisor; research and policy
   scores into intel. All ORACLE-badged.
4. **Ruleset provider** from `DebugGameplay.sqlite` (§7), with its own
   source class and provenance labelling.

## 12. Out of scope

- Civ V, Civ IV, or any other title. The `GameProfile` seam would admit
  one, but nothing here is designed for a third game and it should not be
  claimed to be.
- Multiplayer, hotseat, and scenario rulesets in either game.
- Any write to either game's directories, or to a save file.
- The FireTuner socket and save-file parsing (§3.6).
- Localisation: VI's `DebugLocalization.sqlite` (65 MB) could resolve
  `LOC_*` keys to display text for both games. Deferred; the existing
  key-to-title-case fallback stands.

## Appendix A — Civ VI probe, 2026-09-12

Method: baseline `stat` snapshot of the Civ VI user-data tree with the game
at the main menu (27 files); user played three turns; re-snapshot and diff.

Result: 47 new files, 39 of them CSVs. `Logs/` went from 13 engine logs to
65 files. `Cache/DebugGameplay.sqlite` grew from 5.7 MB to 18 MB. Tuner port 4318 was never open; `AppOptions.txt` had
`EnableTuner 0`, `EnableGameCoreEventLog 0`, and was not modified.

Row counts after three turns: `AI_Research.csv` 6,245; `AI_GovtPolicies.csv`
3,936; `Game_PlayerScores.csv` 341; `Player_Stats.csv` 321;
`AI_Military.csv` 321; `City_BuildQueue.csv` 260; `AI_Victories.csv` 179;
`CombatLog.csv` 35.
