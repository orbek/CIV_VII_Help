# Multi-Game Advisor — Civilization VI alongside Civilization VII

**Date:** 2026-09-12
**Status:** Phases 1, 2a, 2b, 3 and 4 implemented on `feature/multi-game-advisor`
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

`DiplomacySummary.csv`, `AI_Tactical.csv`, `AI_Operation.csv` and
`AI_MayhemTracker.csv` are byte-identical in header between the two
games, and `AI_UnitEfficiency.csv`'s reader pins only shape. All five
were run against the turn-53 Civ VI capture on 2026-09-12 and parsed
unchanged, yielding 95, 3215, 5282, 235 and 133 rows.

`GameCore.log` joins them. An earlier draft of this document put it among
the variant readers on the strength of the turn-3 capture, where every
slot line still read `Civilization - (null)`. That was a capture taken
before the engine had resolved the draft. Civ VI writes the slot block
three times, and the later writes carry the resolved civilization,
leader, level and slot status in exactly Civ VII's format. Verified
2026-09-12 against a turn-53 capture: `read_player_identities` parses Civ
VI's file unchanged and returns all 17 players.

`AI_UnitEfficiency.csv` joins them: its header is the game's own unit
vocabulary and so differs, but the existing reader pins only *shape* — an
empty first cell and a square, non-ragged matrix. VI's matrix is 133×133
and parses unchanged.

All six move to a shared reader module; neither game gets a copy.

### 3.2 Same concept, different columns — VI variant reader (5 files)

| File | Difference |
|---|---|
| `Player_Stats.csv` | VI: `Game Turn, Player, Num Cities, Population, Techs, Civics, Land Units, corps, Armies, Naval Units, TILES: Owned, Improved, BALANCE: Gold, Faith, YIELDS: Science, Culture, Gold, Faith, Production, Food`. Keys rows by **civilization string**, not player id (§5). No towns, settlement cap, urban/rural split, happiness or diplomacy yield. Adds civics, faith, corps, armies. **`Faith` appears twice** — once under `BALANCE:` and once under `YIELDS:`. The reader must address columns by position; anything that builds a dict keyed on column name silently keeps one and discards the other, and which one survives depends on iteration order. |

| `UnitOperations.log` | Header is identical to VII's, but VI interleaves engine diagnostics among the data rows — three lines of the form `Unit operation handler a92585ad, is disabled` in the turn-53 capture, carrying 2 fields where the header declares 5. VII's reader indexes `row[3]` unconditionally and raises `IndexError`. The VI variant skips lines matching that known diagnostic shape and **still raises on any other field-count mismatch**: silently dropping every short row would turn a genuinely malformed log into quiet data loss. |
| `AI_Victories.csv` | VI: `Game Turn, Player, Strategy, Status` — no `Owner`, no `Percentage`, **no weight column**, so `StrategyStatus.weight` is unavailable. **And the Strategy column is a different concept entirely.** VII's values are victory paths (SCIENCE, CULTURAL, MILITARY, ECONOMIC, ESPIONAGE). VI's observed values are era and posture strategies — `STRATEGY_EARLY_EXPLORATION`, `STRATEGY_DARKAGE`, `STRATEGY_ANCIENT_CHANGES`, `STRATEGY_CLASSICAL_CHANGES`, `STRATEGY_MEDIEVAL_CHANGES`, `STRATEGY_INDUSTRIAL_CHANGES`. They do not say which victory a rival is pursuing. Feeding them into `GameState.strategies` would make the victory advisor assert a rival is "Following CULTURAL" on the strength of a row that says nothing of the kind. **Victory-path advice is therefore unavailable in Civ VI** and must be declared unavailable, not approximated. **Phase 3 answered this: it cannot.** Those files score the AI's tech and civic preferences with no victory-condition label, on a scale that is a within-turn priority over currently-available options and so is not comparable across turns or players, naming items that serve every path. They support a descriptive claim — "Cyrus's AI set Writing as its research goal (scored 400.1 of 17 techs it weighed)", "Cyrus's AI scored these civics highest" — and nothing about what a rival is pursuing. Victory-path advice remains unavailable in Civ VI; `GameState.strategies` stays empty for it, and `tests/test_civ6_oracle_guard.py` asserts that no Civ VI claim uses victory vocabulary. |
| `CombatLog.csv` | VI: `Game Turn, Attacking Civ, DefendingCiv, AttackerObjType, DefenderObjType, Attacker Type, Defender Type, AttackerID, DefenderID, AttackerStr, DefenderStr, AttackerStrMod, DefenderStrMod, AttackerDmg, DefenderDmg`. No `Location`, `Destroyed`, `HealAmount`, `attHealth`, `defHealth`. |
| `AI_Operation_Eval.csv` | VI: `Game Turn, Player, Enemy, Operation Name, Value` — **no `Odds` column**. The AI's own odds, which v2 §3.6 made the basis of bounded combat prediction, do not exist in VI. Combat prediction is unavailable in VI and says so. |

**The ownership join is not same-turn.** `AI_CityBuild.csv` does not log
every city every turn: of 807 (turn, city) pairs in the turn-53
`City_BuildQueue.csv` capture, only 202 — 25% — have an `AI_CityBuild`
row for that same turn. Every queue city is resolvable at *some* turn,
and no city changed owner in that capture. So the join must carry the
most recent ownership observed at or before the queue row's turn, not
require a same-turn match; a same-turn join would discard three quarters
of the queue. Carrying forward is also what makes capture work correctly
— ownership changes when `AI_CityBuild` next reports a different player,
and rows before that keep the old owner.

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
The join is built from `GameCore.log`, whose resolved slot lines give
player id, civilization, leader, level and human/AI directly:

```
Player 0: Civilization - CIVILIZATION_ROME (-1806906687)  Leader - LEADER_JULIUS_CAESAR (-197233069), - Level - CIVILIZATION_LEVEL_FULL_CIV, SlotStatus - Human
```

The shared reader already keeps the last resolved line per player and
skips the `(null)` placeholders the engine writes before the draft
resolves, so no VI-specific parsing is needed. Inverting player →
civilization yields the map `Player_Stats` needs.

**Two earlier approaches are recorded here because they look plausible
and are wrong.** Resolving by elimination against the `Civilization
already used:` lines fails: those are emitted only on a draft *conflict*,
and the turn-53 capture has exactly one such line for six majors.
Resolving through the `CIVILIZATION_X::LEADER_Y` draft pool the engine
prints works on that capture — 47 pairs, no ambiguity — but the pool is
printed only when leaders are random, so it vanishes on a hand-picked
draft. The resolved slot line is written either way.

**The remaining ambiguity, and what to do about it.** Civ VI permits two
players to field the same civilization. If a civilization string maps to
more than one player id, the rows under it cannot be attributed, and
those players are reported as unnamed rather than guessed: a wrong
attribution would misfile every observation about that rival, and this
advisor may not assert what it cannot establish.

Levels classify the players directly — no heuristic needed.
`CIVILIZATION_LEVEL_FULL_CIV` is a major, `CIVILIZATION_LEVEL_CITY_STATE`
and `CIVILIZATION_LEVEL_FREE_CITIES` are `PlayerKind.INDEPENDENT`, and
`CIVILIZATION_LEVEL_TRIBE` is the barbarian slot, which is not a player
for advisory purposes. The turn-53 capture had majors at 0-5, city-states
at 6-14, Free Cities at 62 and Barbarians at 63; the id ranges are not
fixed and must be read from the level, never assumed.

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

Moving `guides.json` into a per-game package and adding `--game` to the
link checker is not, by itself, enough to serve a second game's guides.
`civ_advisor/knowledge/catalog.py:160` rejects any entry whose `game` is
not `"civ7"`, and `ALLOWED_HOSTS` (catalog.py:40-41) pins the publisher
markers `(civ7)` and `/civ-vii/`. A `knowledge/civ6/guides.json` therefore
cannot load at all until both are made per-profile. And even once it can
load, it would not reach a player: the two advice-path call sites —
`civ_advisor/advisors/production.py:48` and
`civ_advisor/decisions/context.py:336` — call `load_catalog()` with no
arguments, so they get the module default regardless of which game is
being advised. Only `scripts/check_guides.py` consults
`profile.knowledge_package`. Until the catalog is threaded through the
advice path, the per-game split has no effect on what a player is
actually shown.

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

### 8.1 Choosing the game at runtime

Both games are installed on the same machine and both leave logs on disk,
so a static choice made once at startup is wrong as soon as the player
switches games. Selection is therefore a runtime property, settled two
ways that must agree on precedence:

**Detection.** Each poll, the advisor stats the *gameplay* logs of every
registered game and picks the one whose newest gameplay log is freshest.
It stats only files the profile declares, so an engine log rewritten at
launch cannot masquerade as a game in progress. A game whose logs
directory is absent is not a candidate. When no candidate has been
written within a recency window, the advisor reports that it cannot tell
which game is being played rather than picking the least stale — "I do
not know" is a supported answer here, and guessing would attach a whole
dashboard to the wrong game.

**Override.** The header carries a control naming every registered game
plus Auto. Choosing a game pins it for the session; choosing Auto returns
to detection. An explicit `--game` on the command line starts pinned to
that game, and `--game auto` starts in detection.

The override wins over detection, always and visibly: the header must say
which mode is in force and, when pinned, that detection disagrees if it
does. A pinned choice silently overridden by detection — or detection
silently overridden by a stale pin — would make the advisor's own
provenance claims unreliable, which is the one thing it may not be.

**A game switch is a new sitting.** Swapping the active game changes the
logs directory, the reader table, the capability matrix, the guide
catalog and the context namespace at once. Nothing computed under the
previous game may survive the switch: not the previous turn's snapshot,
not the change-tracking history that "Since last turn" is built from, not
acknowledgements. The existing epoch/sitting machinery already expresses
exactly this, and a switch increments it for the same reason a reload
does — the past being compared against is not this game's past.

**What the switch may not do.** It may not write to either game's
directories, and it may not migrate a player's notes between games. An
acknowledgement made in Civ VII is not an acknowledgement in Civ VI, and
offering it across the boundary would repeat the mistake the reload logic
exists to prevent.

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
2. **Civ VI profile.** Split into two plans; 2a produces a Civ VI game
   state that is testable on its own, 2b makes it reachable from the UI.

   **2a — the data layer.** Readers (§3.1–3.2, §3.5), identity (§5),
   canonical state and the capability guard (§6), fixtures and
   conformance tests (§10). Parity on the overlapping signals; the
   capability matrix honest about amenities, maintenance, deals, combat
   odds and — the largest gap, found while verifying against the turn-53
   capture — victory-path pursuit, which VI's `AI_Victories.csv` does not
   express (§3.2). Reachable only via `--game civ6` at this point.

   "Parity" in this phase therefore means the overlapping signals, not
   every tab. A Civ VI game will legitimately show fewer panels than a
   Civ VII game, and each absent one must say why it is absent.

   **2b — selection and storage.** Runtime detection and the header
   override (§8.1), namespaced archive and context storage (§8), and the
   epoch/sitting handling of a game switch. This is the plan that makes
   the requirements listed immediately below binding.

   `--logs-dir` must be made to imply that `--game` is explicit. Phase 1
   left the two flags decoupled because enforcing it then would have
   changed an error message a pre-existing test asserts on, and the
   hazard cannot arise while only one profile is registered. Once Civ VI
   is registered, a `--logs-dir` pointed at one game's directory while
   the profile is the other's would run the wrong readers and produce
   silently empty advice rather than an error — exactly the failure mode
   this project exists to avoid.

   Every game's profile module must be imported by
   `civ_advisor/games/__init__.py`. Registration happens as an import
   side effect, so a profile whose module nothing imports exists in the
   source but is absent from `profile_ids()`, from `--game`'s help text,
   and from the "this build knows:" error — silently unavailable.

   `LogReader.read` is typed `Callable[[Path], list]` and `load_logs`
   passes exactly one path per reader. Civ VI's build-queue reader (§3.2)
   must join `City_BuildQueue.csv` against `AI_CityBuild.csv` for
   ownership, and §5's identity recovery reads across files too. Neither
   is expressible today. Phase 2 must widen the signature (e.g.
   `read(logs_dir, path)`) rather than let a reader reach for a sibling
   file behind `load_logs`'s back — doing that would report a header
   change in the joined file as a fault against the wrong file, and would
   leave the joined file with no `FileStatus` of its own despite the
   profile depending on it.

   `profile` defaults to `CIV7` in three places (`ingest/load.py`,
   `store.py`, `api/app.py`). Once a second profile exists, any caller
   that forgets the argument runs Civ VII's readers against a Civ VI
   directory: every file reports "file not found" and the user gets
   empty advice instead of an error. Phase 2 must make `profile` required
   at all three layers.

   `LogReader.read` is typed `Callable[[Path], list]` (`civ_advisor/games/base.py`).
   The bare `list` discards the row type each downstream consumer depends on, and
   this is the one place a per-game reader contract could be made checkable — two
   games feeding the same `RawLogs` field must produce the same row type, and
   nothing currently enforces that. Phase 2 should type the return properly when
   it widens the signature for cross-file joins, so the two changes land together
   rather than touching every reader twice.
3. **VI-only signals into existing advisors.** Combat desire and
   diplomatic modifiers into the threat advisor; research and policy
   scores into intel. All ORACLE-badged.
4. **Ruleset provider** from `DebugGameplay.sqlite` (§7), with its own
   source class and provenance labelling.

   Investigated 2026-09-12; full findings in
   `.superpowers/sdd/civ6-ruleset-research.md`. The database splits into two
   confidence regimes and the phase is bounded to the first:

   **Verifiable, and in scope.** Building and district cost, prerequisites,
   maintenance and direct flat yields; technology and civic cost and
   prerequisites; eureka and inspiration triggers (a dedicated `Boosts`
   table); unit cost, combat strength, prerequisites and upgrades. These are
   plain indexed rows. A Library is 90 production, 1 gold maintenance,
   requires a Campus and Writing, and yields a flat +2 Science — stated as
   fact, from the player's own installed files.

   **Not verifiable, and out of scope.** Most conditional and derived
   effects — policy cards, government and wonder special abilities, most
   civic-unlocked perks — exist only as `Modifiers` → `ModifierArguments`
   chains whose argument semantics depend on an `EffectType` the database
   does not catalogue. The Great Library's science modifier records who it
   applies to and when, but not how much. Reading a number out of that
   chain would be inference presented as fact, which is the one thing this
   advisor may not do. These surface as "this exists, the ruleset does not
   state its magnitude", or they do not surface at all.

   **Provenance without a version string.** The database identifies no game
   version, no active DLC and no enabled mods: `PRAGMA user_version` is
   unset and no Version/DLC/Mod/Ruleset table exists. `XP1`/`XP2` table-name
   suffixes imply both expansions are compiled in, but that is inference and
   may not be reported as a ruleset identity. A figure from this source is
   therefore labelled with what IS establishable — that it was read from the
   installed game files, the file's modification time, and a hash of the
   file — which is reproducible and falsifiable even though it is not a
   version number. It may never be labelled "Civ VI <version>".

   Queries run in under 20ms, so lookups happen at recommendation time
   rather than via a startup extract; resolved facts are cached, raw rows
   are not.

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
