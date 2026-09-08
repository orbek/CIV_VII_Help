# Civ VII Turn Advisor v2 — Tactical Intelligence, Local LLM, Grounded Strategy

**Date:** 2026-09-07
**Status:** Implemented on `feature/v2-tactical-intel` (completion audit 2026-09-08)
**Builds on:** `2026-09-07-civ7-turn-advisor-design.md` (v1, shipped on `main`)
**Branch:** `feature/v2-tactical-intel`
**Delivery:** four phases, **one implementation plan per phase**, each
shippable on its own. Phase 1a is planned first; later phases are planned
only after the previous one has landed and its fixture facts are pinned.

## 1. Purpose

v1 reads 7 of the ~86 files Civ VII writes and gives strategic-altitude
advice. A full survey of the log directory (Appendix A) showed that the
game also logs the production queue of every player, every combat with its
strengths and damage, every rival unit's type, tile and current order, the
AI's own operation odds, an 89×89 unit-versus-unit effectiveness matrix,
diplomatic deals including peace, and gossip. v2 uses that data to add:

1. **Wider state** — production, combat outcomes, diplomacy and gossip
   (phase 1a).
2. **A tactical layer** — an enemy unit map, the enemy's actual orders,
   matchup guidance from the game's own matrix, and the AI's own odds
   (phase 1b).
3. **A local LLM layer** — a second opinion, plain-language explanation,
   and a drafted turn plan, generated offline by Ollama (phase 2).
4. **A grounded strategy layer** — recommendation text and thresholds
   verified against real sources and calibrated across every available
   archived game (phase 3).

The product goal is unchanged: **learning**. Every claim carries its
evidence; everything derived from data the game hides is labelled ORACLE
and can be hidden. v2 extends that discipline to the LLM: the model
interprets, the deterministic layer owns every number.

The program remains **read-only with respect to Civ VII's directories**.
v2 writes to exactly one place of its own: an archive directory under the
user's home (§6.3).

## 2. What v1 got wrong, and what changes

Four v1 assumptions were falsified while surveying for v2. Each is a
binding correction.

| v1 assumption | Reality | Consequence |
|---|---|---|
| "Logs are append-only and never truncated." | **Civ VII deletes the entire `Logs/` directory on every launch.** Observed 2026-09-07 17:11: 86 files → 28 engine logs, all gameplay CSVs gone, no archive kept by the game. | Multi-game segment detection is largely moot (a file only ever spans one game process). The dashboard must survive the directory emptying mid-session (it does — v1 §4 per-file isolation). v2 adds an archiver (§6.3) so a game is never lost to a relaunch, and so phase 3 can calibrate across games. |
| "Production queue, unit positions: no data source without a mod." | `CityBuildQueue.csv` logs every player's queue. `AI_Tactical.csv` logs every rival unit's type, tile and order. Your own units' tiles are recoverable from the enemy's targeting (§3.5). | Phases 1a and 1b exist. |
| "No peace detection is expressible." | `DiplomacyDeals.log` records deals with `type Peace`. | The parked v1 finding (war CRITICAL persists after a treaty) is fixable in 1a. |
| "`CombatLog` lets us predict a fight 34–12." | `CombatLog` is historical. Prediction comes instead from `AI_Operation_Eval` (the AI's own odds), `AI_UnitEfficiency` (the game's matchup matrix) and `AI_Commander_Promotions`. | 1b's prediction is sourced from the game, not modelled; and it is bounded (§3.6). |

## 3. Data sources

All headers below were first captured from the live 82-turn game before the
directory was wiped, then reconciled against the preserved turn-100 fixture.
The fixture facts and synthetic hazard tests now pin the observed shapes.

Player 0 remains the human. Rivals are identified from the exact final
player/civilization/leader map in `GameCore.log`, with
`AI_Victories`/`Player_Happiness` as fallbacks; others are independent.
Several files identify players by leader name rather than id. The state
resolver uses that exact map plus known display names; unresolvable names
are kept as text and never guessed to an id.

**Provenance rule for event logs (new in v2):** an event the human took
part in — a combat they fought, a deal they signed, a death of their own
unit — is FAIR, because the game showed it to them. The same event between
two rivals is ORACLE. Gossip is FAIR regardless of parties: it is what the
game chose to tell the player.

### 3.1 Phase 1a — wider state (5 files)

| File | Header (verbatim) | Shape notes | Provenance |
|---|---|---|---|
| `CityBuildQueue.csv` | `Game Turn, Player, City, Production Added, Current Item, Current Production, Production Needed, Overflow` | One row per (turn, player, city). `City` is a `LOC_CITY_NAME_*` key. Sample: `82, 0, LOC_CITY_NAME_MAURYA1, 15.0, BUILDING_BRICKYARD, 47.5, 55, 0.0`. Turns-to-complete = ceil((Needed − Current) / Added), guard Added ≤ 0. | Human's own rows FAIR; rivals' ORACLE |
| `CombatLog.csv` | `Turn, SourceType, Location, AttPlayer, DefPlayer, CombatType, Attacker, Defender, AttStr, DefStr, AttStrMod, DefStrMod, AttDmg, DefDmg, Destroyed, HealAmount, attHealth, defHealth` | **No space after commas** (unlike every other log). `Location` is `(x)(y)`. Observed source types are heal, unit, army, and location; combat types are melee, ranged, or empty for healing. `Destroyed` is Attacker, Defender, District, or N/A; health cells are `(after)before`. | FAIR when the human is a party (you fought it); ORACLE otherwise |
| `Game_Gossip.csv` | `Game Turn, Player, Civilization, Plot X, Plot Y, Type` | **Ragged and unquoted**: 7–14 cells because leader names and detail may contain commas. The reader anchors on the unique `GOSSIP_*` token; all 48 observed types and widths are pinned. `Player` is a leader name, not an id. | **FAIR** — gossip is what the game chooses to tell the player |
| `DiplomacySummary.csv` | `Game Turn, Initiator, Recipient, Action, Details, Mayhem, Visibility` | Every observed row has six cells: the sixth is numeric Mayhem and the advertised Visibility cell is absent. Human-party events are FAIR; rival-only events are ORACLE. | FAIR when the human is a party; ORACLE otherwise |
| `DiplomacyDeals.log` | not CSV | Incoming blocks are proposals. Accepted items occur only under `Turn N, Enacting Deal id …` with `Enacting Deal Item ID …`; the parser deliberately consumes only those blocks. Observed item kinds are `Peace` and `Influence Small Lump (40)`. | FAIR when the human is a party; ORACLE otherwise |

### 3.2 Phase 1b — tactical layer (8 files)

| File | Header (verbatim) | Shape notes | Provenance |
|---|---|---|---|
| `UnitOperations.log` | `Game Turn, Mode, Player, Unit, Operation` | CSV-like; turn is **zero-padded** (`082`). Includes **player 0**. `Unit` is `UNIT_TYPE (unitId)`. Observed modes are `Adding` and `Can't Start`. Builds the human's unit roster: id → type. | FAIR (your own units) |
| `AI_Tactical.csv` | `Game Turn, Player, Category, Target Type, Target Info, Unit Info, Extra` | Players 1–31 only, **never player 0**. `Unit Info` = `UNIT_TYPE (unitId)`; `Extra` embeds coordinates in free text: `Move To: 65 6`, `Fortify: 54 24`. Sample: `81, 30, Defend Camp, , , UNIT_ARCHER (1376263), Fortify: 54 24`. This is the **enemy unit map**. | ORACLE |
| `AI_Operation.csv` | `Game Turn, Player, Operation, Notes, Team, Team Notes, Team Members, Terrain` | Free-text-heavy; coordinates as `x:y` inside `Goal 71:14`, `At 71:15`, `Move 72:14`; named target units: `Target 0, Owner 1, UNIT_SPEARMAN, 71:14`. | ORACLE |
| `AI_CombatPlanning.csv` | `Game Turn, Player, Category, Info` | `Category` ∈ {Initialize Plan, Order, …}; `Order` rows: `Unit 1245192, Move 72:14, Pillage attack`. The AI's **issued** orders. | ORACLE |
| `AI_Operation_Eval.csv` | `Game Turn, Player, Operation, Enemy, Value, Odds` | `Operation` is a numeric operation id; `Enemy` is the operation kind such as `Attack Enemy City`; Odds ∈ [0,1] is the AI's own heuristic. | ORACLE |
| `AI_UnitEfficiency.csv` | first cell empty, then 89 unit type names | A square 89×89 attacker-row/defender-column matrix. Same-type diagonal values are 100; observed values span 0–500. Values are bounded as heuristic ratings, not win probabilities, and recent realized combat can add a disagreement caveat. | ORACLE (the game's internal model) |
| `AI_MayhemTracker.csv` | `Game Turn, Event, Attacker, Unit, Defender, Unit, Mayhem, Current Total` | Two columns named `Unit` (attacker's, defender's). Includes player 0. Sample: `82, Death, 4, DISTRICT_CITY_CENTER, 0, UNIT_WARRIOR, 1.0, 430.0`. | FAIR when the human is a party |
| `AI_Commander_Promotions.csv` | `Game Turn, Player, Commander, Num Promotions, Discipline, Promotion` | Sample: `73, 2, 1638411, 1, LOC_DISCIPLINE_MANEUVER_NAME, LOC_PROMOTION_ARMY_HARASSMENT_NAME`. Real combat modifiers for rival commanders. | ORACLE |

### 3.3 Tier 2 — parse only when an insight needs them

`AI_Market` (gold-purchase offers with coords), `CityPurchase`,
`Balance_Happiness` (per-city unrest events), `Game_CityStates` (suzerain
bonuses), `AI_Leader` (attribute nodes), `AI_CityStrategy`,
`Game_Religion`, `Game_TradeManager`. Real data; no v2 insight requires
them. Adding one is a bounded task, not a phase.

### 3.4 Rejected, with reasons

- `AStar_GC` / `AStar_APP` (3.2 MB) — pathfinding; **zero player-0 rows**;
  `AI_Tactical` already gives rival positions.
- `AI_MovementPlanning` (4.8 MB) and `AI_Behavior_Trees` (3.2 MB) —
  nested per-unit target lists and behaviour-tree traces that duplicate
  `AI_Tactical`/`AI_Operation` at far higher parse cost.
- `AI_Recruiting` (1.5 MB) — repeated `available` rows.
- `RandCalls`, `Profile`, `MemoryUsage`, all `AStar_*`, and the ~30
  engine `.log` files (renderer, audio, network, shaders, metaprogression)
  — no strategic content.
- `Player_Legacies`, `Player_Unlocks`, `AI_Dedications` — header only,
  zero rows in an 82-turn game.
- `Player_WarWeariness` — still no turn column.
- `Game_PlayerScores` — still all zeros.

### 3.5 Recovering the human's unit positions

Player 0 never appears in any `AI_*` or `AStar_*` file, so the human's
tiles are not logged directly. They are recoverable from **the enemy's own
targeting**: `AI_Targets.csv` rows with `Target Owner = 0` and a
`*_PRIORITY_UNIT` type carry the human unit's `Target ID` and `Location`;
`UnitOperations.log` maps that id to a type. Verified on the live game:
target id `917509` at `64:31` on turn 81 joins to `UNIT_ARMY_COMMANDER
(917509)`. Coverage is exactly the units the enemy is tracking — the ones
in danger — which is the coverage that matters. Units not currently
targeted have no known tile and are shown as such.

### 3.6 What combat prediction can and cannot claim

Not available for the human's side: terrain, health except from a recent
`CombatLog` row, promotions except commanders'. Therefore v2 **never
computes a specific fight from first principles**. It reports three
sourced quantities and labels each: the AI's own odds for an operation
(`AI_Operation_Eval`), the game's matchup rating between two unit types
(`AI_UnitEfficiency`, cross-checked against recent realized combat), and the
modifiers a rival commander carries. Wording is bounded to what the source
supports: "the game rates an Archer at 2.1× a Warrior against his
Spearman", never "you win 34–12".

## 4. Phases and their advisors

Every insight keeps the v1 `Insight` contract (stable id, severity,
FAIR/ORACLE provenance, non-empty `title`/`recommendation`/`why`).

### 4.1 Phase 1a — wider state

**New advisor `production.py`**

- `production.own_queue` INFO/FAIR — the human's current item per city
  and turns to complete.
- `production.mismatch` ADVISE/FAIR — the human's current item does not
  address the economy advisor's worst gap (e.g. building a Brickyard while
  food is 41% of the field). Reuses `economy.comparison`; never
  recomputes it.
- `production.rival_military` WARN/ORACLE — a rival's queue turns to
  military production; a **leading indicator** that precedes the
  war-intent score. Threshold: share of a rival's cities producing
  military ≥ `RIVAL_MILITARY_SHARE = 0.5`. "Military" means a
  `Current Item` beginning `UNIT_` whose type is not in
  `CIVILIAN_UNITS = {UNIT_SETTLER, UNIT_MIGRANT, UNIT_FOUNDER, UNIT_SCOUT,
  UNIT_MERCHANT, UNIT_GREAT_*}`; the set is a module constant and is
  extended from the fixture's observed item vocabulary.

**`threat.py` gains**

- `threat.combat_record.{r}` WARN/FAIR when you are losing, INFO otherwise —
  the after-action read from `CombatLog` within `RECENT_TURNS`: fights, your
  losses, their losses, and the latest fight's turn, tile and unit kinds
  ("your Warrior against their Spearman at (62,32)"). Damage figures are not
  quoted until the fixture task pins the log's damage-direction semantics.
  Complements, and does not replace, the Historian-based kill count.
- **Peace detection** — an enacted `DiplomacyDeals` `Peace` item between the human
  and a rival after the last executed `DECLARE_WAR` clears
  `at_war_since`. Closes the parked v1 finding; the "War declared" column
  gains a "peace turn N" state.

**New advisor `intel.py`** — produces no insights of its own in 1a; it
exposes `feed(state) -> list[IntelEvent]`: gossip, diplomatic actions and
combats in one chronological list with per-event provenance. This is the
**Intel tab**. Its purpose is to give fair mode real substance: gossip and
visible diplomacy are game-sanctioned FAIR data.

### 4.2 Phase 1b — tactical layer

**New advisor `tactical.py`**

- `tactical.enemy_units_near.{r}` WARN/ORACLE — rival units within
  `NEAR_TILES = 4` (hex distance) of any of the human's city tiles, with
  types and current orders.
- `tactical.ordered_attack.{r}` CRITICAL/ORACLE — an `AI_CombatPlanning`
  order or `AI_Operation` goal whose target tile is the human's.
- `tactical.matchup` ADVISE/ORACLE — for each threatening enemy unit type,
  the human's best available counter per `AI_UnitEfficiency`, quoted as a
  ratio, with the calibration caveat when realized data disagrees.
- `tactical.odds.{r}` INFO/ORACLE — the AI's own `Odds` for operations
  aimed at the human.
- `tactical.own_exposed` WARN/ORACLE — a human unit whose tile is known
  (§3.5) is within `NEAR_TILES` of a rival unit. ORACLE even though it is
  the player's own unit, because the tile was recovered from the enemy's
  targeting log, which the player cannot see.

**Coordinate layer** (`state/geo.py`): Civ VII uses an odd-row offset hex
grid; distance is axial hex distance after offset→axial conversion. The
orientation is pinned against adjacent move/attack pairs in the preserved
turn-100 fixture.

**Map view**: a fifth panel in the Intel tab rendering known tiles
(human city tiles, human units with known positions, rival units) on a
simple SVG hex grid — no terrain, no fog, no art. Positions only.

### 4.3 Phase 2 — local LLM

- **Runtime:** Ollama over `http://127.0.0.1:11434` (its default). No
  cloud model is ever used; the `:cloud` tags present on this machine are
  excluded by name. Model is a CLI flag `--llm-model`, default
  `gemma4:31b-it-qat` (present locally; 64 GB RAM, M4 Max). If Ollama is
  unreachable or the model absent, the feature is **off** with one quiet
  notice; nothing else changes.
- **Inputs:** a compact JSON of the complete turn (standings, ranked
  insights with their `why`, the intel feed, and in 1b the tactical
  summary) plus the FAIR/ORACLE label on every item. **The model never
  receives raw logs and never computes numbers**; every figure it may
  cite is already in the deterministic layer's output.
- **Outputs**, cached by complete turn and prompt hash, generated in a background
  worker after `Store.rebuild()` so the board never waits:
  1. `second_opinion` — the model's independent read of the turn, shown
     beside the rules verdict so agreement and disagreement are visible.
  2. `explain` — for the top `EXPLAIN_TOP_N = 3` insights, a plain-language
     expansion: why it matters, what happens if ignored, alternatives.
  3. `turn_plan` — an ordered plan for the turn, each step naming the
     insight it comes from.
- **Provenance:** LLM output is a separate `Commentary` type (not an
  `Insight`) carrying `model`, `prompt_hash`, `turn`, and a
  `saw_oracle: bool`. v2 generates from the full state, so commentary is
  **hidden in fair mode** — the model saw intercepts. A later flag may add
  a fair-only generation; not in v2.
- **Guardrails:** output is rendered as text, never executed or parsed
  into actions; a generation that exceeds `LLM_TIMEOUT_S = 90` is
  abandoned and the panel says so; the prompt asks the model to cite the
  insight id for every claim, and the UI dims any sentence that cites
  none.

### 4.4 Phase 3 — grounded strategy

- Research current mechanics with web sources (wiki, patch notes,
  Civilopedia dumps) — the game ships no readable rules database (its
  `Prebuilt database not found` log line; rules are built at runtime from
  packed assets).
- Deliverable is a **findings document first**: every recommendation
  string and every threshold, with a verdict (confirmed / corrected /
  unknown) and a source. Corrections then land as ordinary reviewed tasks.
  **No threshold changes without a written rationale.**
- Thresholds are recalibrated against **every archived game** (§6.3),
  not one; the calibration script is committed so it can be re-run.

## 5. Architecture

Unchanged layering: `ingest/` → `state/` → `advisors/` → `store.py` →
`api/` → `web/`. Additions:

- `ingest/`: 14 new readers (5 in 1a, 8 in 1b, plus the GameCore identity
  reader closed in the completion audit); `LOG_FILES` grows
  accordingly; `load_logs` isolation unchanged. `csvfile.read_table` is
  **not** changed for `CombatLog`'s no-space commas: `read_table` already
  strips every cell, so the existing reader path handles both spacings;
  the `CombatLog` reader's own tests pin that. `DiplomacyDeals.log` gets a
  dedicated block parser in `ingest/textlogs.py`; the CSV-shaped
  `UnitOperations.log` is parsed with the other tactical diagnostic streams
  in `ingest/tactical.py`.
- `state/`: `GameState` gains `build_queues`, `combats`, `gossip`,
  `diplomacy_events`, `deals`, `peace_turns`; in 1b it carries the raw
  `unit_operations`, `tactical`, `operations`, `combat_orders`,
  `operation_evals`, `unit_efficiency`, `mayhem`, and
  `commander_promotions` rows, with derived tactical views owned by the
  advisor, plus `geo.py`. A `names.py` resolver maps leader name → id.
- `advisors/`: `production.py`, `intel.py` (1a); `tactical.py` (1b).
  `ADVISORS`, `ADVISOR_ORDER` and the `app.js` tab set are pinned by the
  existing consistency test — extending it is part of each phase.
- `llm/` (2): `client.py` (Ollama HTTP), `prompts.py`, `worker.py`
  (background generation + per-turn cache), `models.py` (`Commentary`).
  Imports `state.models` and `advisors.base` only.
- `api/`: `/api/intel`, `/api/tactical` (1b), `/api/commentary` (2).
- `web/`: Intel tab (1a), map view (1b), LLM panels (2). The Oracle
  toggle's fair/oracle column sets are extended and re-pinned.

## 6. Error handling

### 6.1 Per-file isolation
Unchanged from v1 §4. A new log that is missing degrades exactly the
features that need it; the UI chip names the file.

### 6.2 The directory wipe
On game launch the `Logs/` directory is emptied. The poller sees every
snapshot entry go to `None`, rebuilds to an empty state, and the page
shows "Nothing to report yet" with 7+ "not readable" chips. This is
correct behaviour and is already tested (v1 final review, empty-directory
scenario). v2 adds one line of copy: "Civ VII clears its logs when it
starts — advice resumes once a game is loaded."

### 6.3 The archiver
Because the game deletes its logs, v2 mirrors them. On every rebuild,
`Store` copies every `.csv` and `.log` file to
`~/.civ7-advisor/archive/<game-key>/<session>/`. `game-key` comes from the
last `Random Seeds: Game …, Map …` line in `GameCore.log`, which is stable
for a save; `session` keeps each lifetime of the game's Logs directory
separate so a later reload cannot overwrite earlier history. Unknown seeds
use `unknown-game`. Writes go **only** below that archive root; the Civ VII
tree is never touched. Archiving is on by default, `--no-archive` disables
it, and the CLI gains `civ7-advisor archive list`. Phase 3 selects the most
advanced session once per game for calibration.

### 6.4 LLM failures
Ollama down, model missing, timeout, malformed output: the commentary
panel shows one sentence saying which, the rest of the board is
unaffected, and the failure is logged once per distinct evidence prompt
(not per poll).

## 7. Testing

- **Fixture:** `tests/fixtures/logs_v2/` — the preserved turn-100 session,
  including combat, accepted deals, tactical streams, and a compact
  `GameCore.log` identity excerpt. The v1 fixture stays for v1 tests.
- Each reader: header/shape test, row-count and spot-value tests against
  the fixture, and a synthetic test for every hazard named in §3
  (no-space commas, ragged gossip, zero-padded turns, leader-name
  resolution, `DiplomacyDeals` block parsing).
- `geo.py`: offset conversion and hex distance pinned against known
  adjacent move/attack coordinates from the fixture.
- Advisors: hand-built states at each threshold boundary (both sides), as
  in v1; fixture-based expectations recorded once the fixture exists.
- Oracle gating: the existing column-set pin is extended to the Intel
  tab, the map, and the commentary panel; a DOM-level assertion that no
  ORACLE-labelled event or commentary is rendered in fair mode.
- LLM: `client.py` tested against a fake Ollama server (httpx
  `MockTransport`); prompts tested for the "cite an insight id"
  contract; no test calls a real model.
- Archiver: writes only under the archive root (asserted), idempotent
  per turn, never touches the source directory (asserted by mtime).

## 8. Out of scope for v2

- First-principles combat simulation (no human-side terrain/health).
- Any Civ VII mod, and any read of the packed game assets.
- Cloud LLMs, and any network call other than to `127.0.0.1:11434`.
- Multiplayer.
- Tier 2 files (§3.3) until an insight needs one.
- A fair-only LLM generation (recorded as a candidate flag).

## 9. Tooling

Unchanged: Python 3.12, `uv`, `fastapi`, `uvicorn`; dev `pytest`,
`httpx`. Phase 2 adds **no** dependency — Ollama is called over HTTP with
`httpx`, which is already present as a dev dependency and is promoted to a
runtime dependency in phase 2 (the one allowed dependency change).

---

## Appendix A — Survey of all 86 files in `Logs/` (2026-09-07, 82-turn game)

Tier: **1** = wire (phase), **2** = parse when an insight needs it,
**3** = skip. Sizes as observed.

| File | Size | Tier | Notes |
|---|---|---|---|
| AI_MovementPlanning.csv | 4.8 MB | 3 | Nested per-unit target lists; duplicates AI_Tactical/AI_Operation at high parse cost |
| AI_Behavior_Trees.csv | 3.2 MB | 3 | Behaviour-tree traces (`Independent Power Assault, RUNNING, Goal 71:14`); duplicates AI_Operation |
| AI_Targets.csv | 2.9 MB | 1 (v1) | Already wired; in 1b also yields human unit tiles (§3.5) |
| AStar_GC.csv | 2.9 MB | 3 | Pathfinding From/To per unit; zero player-0 rows |
| AI_Recruiting.csv | 1.5 MB | 3 | Repeated `available` rows |
| net_message_debug.log | 1.4 MB | 3 | Network |
| Metaprogression.log | 1.4 MB | 3 | Account progression |
| UnitOperations.log | 962 KB | 1 (1b) | Human unit roster; zero-padded turns |
| AI_Operation.csv | 928 KB | 1 (1b) | Operations with coords and named targets |
| UI.log | 848 KB | 3 | UI engine |
| AI_Tactical.csv | 649 KB | 1 (1b) | Enemy unit map |
| Balance_Identity.csv | 645 KB | 2 | Attribute points per turn (`Wildcard, TURN START`) |
| twokdna.log | 551 KB | 3 | Telemetry |
| RandCalls.csv | 429 KB | 3 | RNG audit |
| AStar_APP.csv | 356 KB | 3 | Pathfinding; zero player-0 rows |
| ArtDef.log | 336 KB | 3 | Art definitions |
| AI_CombatPlanning.csv | 324 KB | 1 (1b) | Issued orders |
| Player_Stats.csv | 313 KB | 1 (v1) | |
| Game_Gossip.csv | 212 KB | 1 (1a) | FAIR intel; ragged 6/7; leader names |
| Scripting.log | 153 KB | 3 | Script engine |
| AI_DiplomaticActions.csv | 131 KB | 1 (v1) | |
| NarrativeStories.log | 131 KB | 3 | Narrative event eligibility (`Requirements met for story 3276A`); no coords or outcomes |
| GameCoreAppConfig.log | 120 KB | 3 | Config dump |
| CloudPrograms.log | 116 KB | 3 | Cloud |
| Profile.csv | 83 KB | 3 | Perf profile |
| Player_Treasury.csv | 75 KB | 1 (v1) | |
| CombatLog.csv | 73 KB | 1 (1a) | Realized combat; no-space commas |
| AI_UnitEfficiency.csv | 61 KB | 1 (1b) | 89×89 matchup matrix |
| Serializer.log | 58 KB | 3 | Save serializer |
| DiplomacySummary.csv | 57 KB | 1 (1a) | Actions + Visibility |
| AI_Market.csv | 45 KB | 2 | Gold-purchase offers with coords |
| AI_Operation_Eval.csv | 44 KB | 1 (1b) | AI's own odds |
| CityBuildQueue.csv | 43 KB | 1 (1a) | Production queues, all players |
| Modding.log | 42 KB | 3 | Asset package loads |
| AI_MayhemTracker.csv | 41 KB | 1 (1b) | Combat deaths incl. player 0 |
| Audio.log | 36 KB | 3 | |
| PlayerScore.log | 33 KB | 3 | Score internals (scores are 0) |
| Independents.csv | 30 KB | 2 | Tribe actions |
| Localization.log | 26 KB | 3 | |
| Game_PlayerScores.csv | 24 KB | 3 | All zeros |
| AI_Behavior_Tree_Events.csv | 24 KB | 3 | Tree start/stop events |
| AudioCiv.log | 19 KB | 3 | |
| Layout.log | 19 KB | 3 | |
| Player_Happiness.csv | 17 KB | 1 (v1) | |
| Historian.csv | 14 KB | 1 (v1) | |
| Renderer.log | 14 KB | 3 | |
| AudioContext.log | 12 KB | 3 | |
| Game_RandomEvents.csv | 11 KB | 2 | Volcanoes/floods with coords and damage |
| GameCore.log | 10 KB | 1 (archive/1b) | Save seeds plus exact player/civilization/leader identity map |
| MemoryUsage.log | 7 KB | 3 | |
| AI_CityStrategy.csv | 7 KB | 2 | Per-city AI strategy weights |
| AI_Victories.csv | 6 KB | 1 (v1) | |
| GraphicSettings.log | 4 KB | 3 | |
| AppStateLoadGame.log | 4 KB | 3 | |
| VFXSystem.log | 4 KB | 3 | |
| General.log | 4 KB | 3 | Launch log (source of the "no prebuilt database" fact) |
| CityPurchase.csv | 4 KB | 2 | Gold purchases |
| Startup.log | 3 KB | 3 | |
| Database.log | 3 KB | 3 | |
| DiplomacyManager.csv | 3 KB | 3 | Session open/close only (`?, ?, ?, Closing Session`) |
| net_connection_debug.log | 2 KB | 3 | |
| Game_Greatworks.csv | 2 KB | 2 | Great works |
| T2GP.log | 2 KB | 3 | Publisher services |
| MotD.log | 2 KB | 3 | |
| AppLogging.log | 1 KB | 3 | |
| DiplomacyDeals.log | 1 KB | 1 (1a) | Deals incl. Peace |
| Game_Religion.csv | 1 KB | 2 | Pantheon/religion adoption |
| AI_Leader.csv | 1 KB | 2 | Attribute nodes chosen |
| Game_TradeManager.csv | 895 B | 2 | Trade routes and resources |
| Engine.log | 815 B | 3 | |
| AI_Commander_Promotions.csv | 659 B | 1 (1b) | Commander promotions |
| Game_GreatPeople.csv | 548 B | 2 | Great people |
| Player_WarWeariness.csv | 429 B | 3 | No turn column |
| Game_CityStates.csv | 397 B | 2 | Suzerain bonuses |
| AdvancedStart.csv | 385 B | 3 | Turn-1 spawns only |
| Balance_Happiness.csv | 384 B | 2 | Per-city unrest events |
| net_transport_debug.log | 311 B | 3 | |
| AutoArchive.csv | 298 B | 3 | Engine sync noise, not a CSV |
| Game.log | 201 B | 3 | |
| JsonParser.log | 67 B | 3 | |
| networkservices.log | 56 B | 3 | |
| CodeRedemption.log | 42 B | 3 | |
| AI_Dedications.csv | 37 B | 3 | Header only |
| Player_Unlocks.csv | 27 B | 3 | Header only |
| Player_Legacies.csv | 27 B | 3 | Header only |
| GameCoreAppMetagaming.log | 0 B | 3 | Empty |

**Wipe observation:** after a fresh launch at 17:11 the directory held 28
files, all engine logs recreated at launch; every gameplay CSV above was
gone. Gameplay CSVs appear only once a save is loaded.
