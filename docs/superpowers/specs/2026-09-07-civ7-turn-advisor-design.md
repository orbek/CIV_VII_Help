# Civ VII Turn Advisor — Design

**Date:** 2026-09-07
**Status:** Approved for planning (revised after verifying every log file against a live game)
**Scope:** Version 1

## 1. Purpose

A second-screen web dashboard that watches a running single-player game of
Sid Meier's Civilization VII, reads the game's own per-turn log files, and
each turn shows (a) where every rival stands, (b) which rivals are a threat
and why, (c) who is pursuing and leading each legacy path, (d) how the
player's economy compares to the field, and (e) a ranked list of
recommended actions for the turn — each with the evidence that produced it.

The product goal is **learning**, not winning by proxy. Every
recommendation exposes its reasoning, and advice derived from information
the game hides from the player is visibly labeled as such, so the player
can compare their own read of the game with what was actually happening.

This is for offline, single-player use against the game's AI. It reads
files only; it never writes to any Civ VII directory and never modifies
the game.

## 2. Data source

Civ VII writes live telemetry to
`~/Library/Application Support/Civilization VII/Logs/`. The files are
CSV, append-only, flushed as each player finishes a turn, and are
**not** reset when a new game starts.

Files used in v1. Every column below was verified against a live 82-turn
game on this machine (player 0 = human, seven rival leaders, ~24
independent peoples).

| File | Row = | Columns (verbatim header) | Used for |
|---|---|---|---|
| `Player_Stats.csv` | (turn, player), all players | ragged — see hazard 1 | cities, towns, settlement cap, population, techs, land/naval units, tiles, gold balance, seven yields |
| `Player_Treasury.csv` | (turn, player), all players | `Turn, Player, Gold Balance, Unit Maintenance, Building Maintenance, Total Maintenance, Gold Yield` | net gold per turn |
| `Player_Happiness.csv` | (turn, player), **majors only (0–7)** | `Game Turn, Player, Golden Age, Threshold, Total Happiness, Per Turn Happiness, Happiness Bonus` | celebration progress = Total/Threshold; `Golden Age` is `Yes`/`No` |
| `AI_Victories.csv` | strategy **change event** (AI players) | `Game Turn, Player, Owner, Strategy, Status, Percentage` | which legacy path each AI is pursuing. `Status` ∈ Following/Stopped/Forbidden. `Percentage` is the AI's **priority weight** for that strategy (observed 25–100), not progress toward victory |
| `AI_DiplomaticActions.csv` | (turn, AI player, action) | `Game Turn, Player, Diplomatic Action, Target, Score` | scored candidate actions and executed actions, incl. `DECLARE_WAR` against a target — see hazard 4 |
| `AI_Targets.csv` | (turn, AI player, target plot) | `Game Turn, Player, Target Type, Unit Type, Target Owner, Target ID, Location` | which plots the AI is targeting; `Location` is `X:Y`. `TARGET_ENEMY_CITY` rows with `Target Owner` 0 are the AI targeting the human's city tiles |
| `Historian.csv` | game event | `Type, Age, Turn, X, Y, Player, Opponent, Unit, Constructible` | `UNIT_KILLED`/`SHIP_SUNK` between human and a rival = an active front — see hazard 5 |

Examined and rejected for v1: `Game_PlayerScores.csv` (every score is 0
in the live game — Civ VII does not use a classic score) and
`Player_WarWeariness.csv` (no turn column, so rows cannot be placed in
time or separated by game).

Player identity: player `0` is the human (never appears in `AI_*` files).
Players whose `Owner` in `AI_Victories.csv` is a `LOC_LEADER_*_NAME` key,
or who appear in `Player_Happiness.csv`, are rival civilizations. Players
whose owner is `LOC_CIVILIZATION_INDEPENDENT_NAME`, or who appear in
neither, are independent peoples and are excluded from rival rankings and
threat analysis.

### 2.1 Verified hazards the ingest layer must handle

1. **Ragged header in `Player_Stats.csv`.** The header has 22 names; data
   rows have 25 columns. `TILES:`, `BALANCE:`, `YIELDS:` and `BY TYPE:`
   are group labels, not columns. The parser maps columns **by
   position** (0-based): 0 turn, 1 player, 2 cities, 3 towns,
   4 settlement cap, 5 settlements over cap, 6 urban pop, 7 rural pop,
   8 techs, 9 land units, 10 naval units, 11 tiles owned, 12 tiles
   improved, 13 gold balance, 14 science, 15 culture, 16 gold,
   17 production, 18 food, 19 happiness, 20 diplomacy, 21–24 unlabeled
   by-type breakdown (ignored). Cross-checked at turn 82 / player 0:
   col 13 = 136.0 = Treasury `Gold Balance`; col 16 = 23.0 = Treasury
   `Gold Yield`; col 19 = 20 = Happiness `Per Turn Happiness`. The
   parser raises on any row whose column count is not 25 and never
   trusts this file's header.
2. **Partial turns.** Rows for turn *N* arrive one player at a time.
   `Player_Stats.csv` may be at turn 82 for player 0 while `AI_*` files
   are still on turn 80–81. A turn is treated as complete only once any
   row for the *following* turn exists in `Player_Stats.csv`, so
   `complete_through_turn = latest_turn - 1`. This is the state at the
   start of the human's current turn, which is exactly what the advice
   should be based on. The UI shows the in-progress turn as such.
   Checking "every rival has a row" does **not** work, because
   eliminated players simply stop appearing.
3. **Eliminated players.** A rival whose last `Player_Stats` row is
   older than `complete_through_turn` is marked `alive = False` and is
   excluded from rankings and threat analysis, but kept in the player
   list so historical events still resolve to a name. Live game:
   Napoleon (player 3) last appears at turn 59.
4. **Three row shapes in `AI_DiplomaticActions.csv`.** The third
   column is one of: `DIPLOMACY_ACTION_*` (a scored candidate action),
   `LOC_DIPLOMACY_ACTION_*_NAME` (same meaning, localized-key variant),
   or `ACTION DIPLOMACY_ACTION_*` with a fifth column `TOKENS n` (the
   action was **executed**). The reader normalizes all three to one row
   type with `kind: SCORED | EXECUTED` and a canonical action name
   (`DECLARE_WAR`, `OPEN_BORDERS`, …) with all prefixes/suffixes
   removed. A target of `-1` means unknown and becomes `None`; it is
   never treated as the human. Live game: players 1 and 4 hold
   `SCORED DECLARE_WAR` against player 0 at ≈202–204 for turns 72–81
   (committed AIs sit near 200; uncommitted ones at 25–75), and player
   4 has an `EXECUTED DECLARE_WAR` with target 0 at turn 80.
5. **`Historian.csv` kill semantics.** For `UNIT_KILLED`/`SHIP_SUNK`,
   `Player` is the **owner of the unit that died** and `Opponent` is
   the killer. Verified: player 7 (Catherine, Greece) loses a `Hoplite`;
   player 4 (Rizal, Maya) loses a `Jaguar Slayer`. `Opponent` `-1`,
   `Unit` `NO_UNIT` and `Constructible` `NO_CONSTRUCTIBLE` become
   `None`.
6. **`AI_Victories.csv` is event-based.** Rows appear only when an AI
   changes a strategy's status. The state layer folds rows in turn
   order into the *current* status per (player, strategy), keeping the
   turn of the last change as `since_turn`. Strategy names are
   canonicalized to their last `_` segment: `CD_VICTORY_STRATEGY_SCIENCE`
   → `SCIENCE`, `TRIUMPH_STRATEGY_ALLAGES_ESPIONAGE` → `ESPIONAGE`.
7. **Multi-game files.** Because logs are never truncated, a file
   contains every game played since install. A new game is detected
   when the turn number in a file drops below the previous row's turn.
   Only the most recent game segment is exposed. (Should Civ VII reset
   the turn counter at an Age transition, this rule would discard the
   previous Age — acceptable, since legacy paths reset per Age.)
8. **Lag between files.** Different files reach a given turn at
   different times. The state layer joins on turn number and tolerates
   missing rows for the newest turns rather than assuming alignment.
9. **Localized keys.** Leader names arrive as `LOC_LEADER_CONFUCIUS_NAME`.
   A small static dictionary maps known keys to display names; unknown
   keys fall back to title-casing the middle of the key.

## 3. Architecture

Single Python process, run with `uv run civ7-advisor`, no build step,
no network access required at run time.

```
Civ VII Logs/*.csv
        │  mtime/size polling every 1 s (asyncio task)
        ▼
  civ7_advisor/ingest/     one reader per file → typed row dataclasses;
                           load_logs() with per-file error isolation
        ▼
  civ7_advisor/state/      build_state(raw) → GameState (current game only)
        ▼
  civ7_advisor/advisors/   pure functions GameState → list[Insight]
                           (+ summaries the UI tables reuse)
        ▼
  civ7_advisor/store.py    holds GameState + ranked insights; rebuilds on
                           change; fan-out to SSE subscribers
        ▼
  civ7_advisor/api/        FastAPI: /api/state, /api/insights, /events (SSE)
        ▼
  civ7_advisor/web/        static index.html + style.css + app.js
```

Dependencies point strictly downward. `advisors/` imports only
`state.models` and knows no file paths. `api/` is the only layer that
knows about HTTP. This is what keeps the planned **B evolution** cheap:
SQLite persistence would sit behind `store.py`; a separate React frontend
would consume the same `/api` routes.

Polling was chosen over `watchdog`: seven `stat()` calls a second is
free, it needs no extra dependency, and it avoids cross-thread
debouncing.

### 3.1 `ingest/`

- `csvfile.py` — `read_table(path)` (csv module, `skipinitialspace`,
  cells stripped, blank lines dropped), `latest_game_segment(rows,
  turn_col)` (hazard 7), and `LogFormatError`.
- `columns.py` — the pinned positional column map and expected column
  count for `Player_Stats.csv` (hazard 1).
- `readers.py` — one function per log file returning typed frozen
  dataclasses: `read_player_stats`, `read_treasury`, `read_happiness`,
  `read_victories`, `read_diplomacy`, `read_targets`, `read_historian`.
  Fixed-shape files have their header compared to the verbatim header
  above and raise `LogFormatError` on mismatch.
- `load.py` — `load_logs(logs_dir) -> RawLogs`: runs every reader,
  isolating failures per file (§4), and records a `FileStatus` per
  file.
- `poller.py` — `watch(logs_dir, names, on_change, interval)`: an
  asyncio loop comparing an `(mtime_ns, size)` snapshot of the seven
  files and calling `on_change` in a worker thread when it differs.

### 3.2 `state/`

- `models.py` — `PlayerKind` (`HUMAN | RIVAL | INDEPENDENT`), `Player`
  (id, name, kind, alive, last_seen_turn), `PlayerTurn` (the
  `Player_Stats` row merged with that turn's treasury and happiness
  rows; properties `settlements`, `military_units`, `net_gold`,
  `celebration_progress`), `StrategyStatus` (player, strategy, status,
  weight, since_turn), and `GameState` with `players`, `latest_turn`,
  `complete_through_turn`, `turns[turn][player]`,
  `strategies[player][strategy]`, `intents`, `targets`, `events`,
  `files`, plus helpers `human()`, `rivals(alive_only=True)`,
  `majors()`, `at(player, turn=None)`, `series(player, attr, n)`.
  Intent/target/event rows are the ingest dataclasses re-exported.
- `build.py` — `build_state(raw: RawLogs) -> GameState` plus the
  `LEADER_NAMES` dictionary and `display_name(key)`.

### 3.3 `advisors/`

```python
class Provenance(Enum):
    FAIR = "fair"      # derivable from what the player can see in-game
    ORACLE = "oracle"  # uses AI-internal data the game hides

class Severity(IntEnum):
    INFO = 0; ADVISE = 1; WARN = 2; CRITICAL = 3

@dataclass(frozen=True)
class Insight:
    id: str            # stable key, e.g. "threat.war_intent.1"
    advisor: str       # "threat" | "victory" | "economy"
    severity: Severity
    provenance: Provenance
    title: str
    recommendation: str
    why: str           # evidence, plain language, with numbers
    turn: int          # complete_through_turn it was computed on
    subject_player: int | None = None
```

Each advisor module exposes `advise(state) -> list[Insight]` and a
summary function the API reuses for its tables, so table numbers and
insight numbers can never disagree. Tunable thresholds are module-level
named constants — plain Python, no config DSL.

Rival `Player_Stats` comparisons are classed FAIR: the in-game Rankings
and leader screens expose relative yields and military strength closely
enough that a player could reach the same read. AI intent, targeting,
strategy weights and rival happiness are ORACLE.

- **`threat.py`** — `summarize(state) -> list[RivalThreat]` (per alive
  rival: land units, ratio to human, latest scored war score against
  the human and how long it has held, executed war in the last
  `RECENT_TURNS`, kills/losses against the human in that window with
  the latest fight's location, and the human plots the rival's AI is
  targeting this turn). Insights:
  `threat.at_war.{r}` CRITICAL/ORACLE on an executed `DECLARE_WAR`
  against the human within `RECENT_TURNS = 10`;
  `threat.active_front.{r}` WARN/FAIR on kills between the two in that
  window; `threat.war_intent.{r}` WARN/ORACLE when the latest scored
  war intent ≥ `WAR_INTENT_WARN = 100` (INFO when ≥ `WAR_INTENT_WATCH =
  50`), with the first turn of the current run, suppressed when
  already at war; `threat.targeting.{r}` WARN/ORACLE when the rival's
  AI lists the human's city tiles as `TARGET_ENEMY_CITY` (ADVISE if
  only units), with count and bounding box;
  `threat.military_gap.{r}` ADVISE/FAIR when rival land units ≥
  `MILITARY_RATIO_ADVISE = 1.5` × human; `threat.army_growth.{r}`
  INFO/FAIR when the rival gained ≥ `ARMY_GROWTH_DELTA = 3` more land
  units than the human over `ARMY_GROWTH_TURNS = 10`.
- **`victory.py`** — `PATH_STATS` maps legacy paths to their FAIR
  proxy stat: SCIENCE→science yield, CULTURAL→culture yield,
  ECONOMIC→gold yield, MILITARY→military units. `leaderboards(state)`
  ranks alive majors (human included) per path. Insights:
  `victory.pursuing.{r}.{path}` INFO/ORACLE for each rival strategy
  `Following` with weight ≥ `STRATEGY_COMMITTED = 75`;
  `victory.leader.{path}` ADVISE/FAIR when a rival leads the proxy stat
  by ≥ `LEAD_MARGIN = 1.25` × the runner-up, its `why` carrying only the
  two yields and the ratio; `victory.leader_committed.{path}`
  WARN/ORACLE **alongside** it when that leader's AI is also committed
  to the same path, its `why` carrying only the strategy weight. Two
  insights rather than one that escalates: escalating the single insight
  to ORACLE removed fair-derivable evidence from fair mode — a rival
  leading culture 60 vs 20 while committed produced no victory insight
  at all with the toggle off, though the 3× lead sits in plain FAIR data
  in the leaderboard table below it — which contradicts the toggle's
  purpose. `victory.you_lead.{path}` INFO/FAIR when the human leads.
- **`economy.py`** — `comparison(state) -> list[YieldComparison]`
  (human value, rival median, leader, ratio for science, culture, gold,
  production, food). Insights: `economy.behind.{stat}` for each stat
  with ratio < `BEHIND_RATIO = 0.75` — the worst one is WARN (ratio <
  `FAR_BEHIND_RATIO = 0.5`) or ADVISE, the rest INFO, each with a
  stat-specific Civ VII lever as the recommendation;
  `economy.settlement_slack` ADVISE/FAIR when settlements < cap;
  `economy.over_cap` WARN/FAIR when over cap; `economy.negative_gold`
  WARN/FAIR when gold yield − total maintenance < 0;
  `economy.celebration` INFO/FAIR when the human's celebration progress
  ≥ `CELEBRATION_NEAR = 0.9`; `economy.rival_celebration.{r}`
  INFO/ORACLE for rivals at the same threshold.
- **`checklist.py`** — `rank(insights)`: order by severity desc, turn
  desc, advisor order (threat, victory, economy), id; dedupe by `id`.
- **`__init__.py`** — `run_all(state)` runs the three advisors and
  returns `rank(...)`.

### 3.4 `store.py` and `api/`

- `Store(logs_dir)` — `rebuild()` runs `load_logs → build_state →
  run_all` and swaps `state`/`insights` atomically; `subscribe()` /
  `unsubscribe()` hand out `asyncio.Queue`s; `publish(event)` fans out.
- `create_app(logs_dir, poll_interval)` — FastAPI app whose lifespan
  performs one synchronous rebuild, then starts the poller; each change
  rebuilds and publishes `{"type": "state_changed", "turn": N}`.
- `GET /api/state` — latest/complete turn, `in_progress`, `standings`
  (every major: name, kind, alive, `PlayerTurn` at the complete turn,
  current strategies), `ranks` (human's rank / count among alive majors
  for science, culture, production, gold, military units), `threats`
  (from `threat.summarize`), `leaderboards`, `economy` (from
  `economy.comparison`), `files`.
- `GET /api/insights` — ranked `list[Insight]` as JSON (enums as
  names).
- `GET /events` — SSE; `data: {...}` on change, `: keepalive` every
  15 s. Browser refetches both JSON routes on each event.
- `GET /` → `web/index.html`; `/static/*` → the web directory.

### 3.5 `web/`

One page, dark theme, vanilla JS, no framework, no bundler. Header strip
always visible: turn (with an "in progress" badge when `latest_turn >
complete_through_turn`), rank chips (Science #7/7 · Culture #7/7 ·
Production · Gold · Military), the single highest-severity insight, an
**Oracle toggle**, and file-status warning chips. Four tabs:

1. **Checklist** — ranked insight cards.
2. **Threats** — rival table from `threats` plus threat insights.
3. **Victory** — rival strategies and per-path leaderboards plus
   victory insights.
4. **Economy** — human vs median vs leader per yield plus economy
   insights.

Every insight card shows `title`, `recommendation`, and `why` inline.
ORACLE insights get a distinct border and an "Oracle" badge; the Oracle
toggle **hides every ORACLE insight** (remembered in `localStorage`) so
the player can check whether fair-play evidence alone reaches the same
conclusion.

## 4. Error handling

- A malformed row in any log file (`LogFormatError` or a parse
  `ValueError`) is logged with file name and reason, and that **file's**
  rows are dropped for that rebuild; other files still produce state.
  `FileStatus.ok = False` for it, and the UI shows a warning chip naming
  the degraded file.
- `Player_Stats.csv` column-count mismatch is fatal for that file (never
  guessed), with a message telling the user the game version may have
  changed the log format and which file to update.
- A missing log file yields an empty row list and `FileStatus` "file
  not found"; if `Player_Stats.csv` is missing or empty, `GameState` is
  empty (`latest_turn = 0`, no players) and advisors return nothing.
- If the `--logs-dir` directory does not exist, the CLI exits with
  status 2, printing the path it looked for and the flag to change it.
- SSE clients that disconnect are dropped silently; the page
  reconnects automatically.

## 5. Testing

- `tests/fixtures/logs_82turns/` — a snapshot of the seven real log
  files from the live game on this machine (Player_Stats 2523 rows,
  AI_Targets 47 025 rows, ≈3.5 MB). It contains the ragged header, the
  partial turn 82, an eliminated player, an executed war declaration
  against the human, and all three diplomacy row shapes.
- `ingest/` tests: each reader parses the fixture; row counts and
  spot-checked values match hand-verified numbers (turn 82 / player 0:
  science 15.0, gold balance 136.0, gold yield 23.0, land units 4;
  diplomacy: 117 EXECUTED rows, the turn-80 player-4 `DECLARE_WAR`
  executed with target 0, target `-1` → `None`; happiness rows only for
  players 0–7; historian first/last rows); `Player_Stats` with a 24-
  column row raises; a synthetic two-game file yields only the second
  game; a header mismatch raises.
- `state/` tests: fixture gives `latest_turn == 82`,
  `complete_through_turn == 81`; players 1,2,4,5,6,7 RIVAL and alive;
  player 3 "Napoleon" RIVAL, `alive == False`, `last_seen_turn == 59`;
  player 9 INDEPENDENT; `at(0, 81)` has land units 5, science 15.0 and
  merged treasury/happiness fields; `strategies[4]["CULTURAL"]` is
  Following, weight 100, since turn 74; `strategies[1]["CULTURAL"]` is
  Stopped since turn 80; `series(0, "land_units", 3) == [7, 6, 5]`;
  empty stats → empty state.
- `advisors/` tests: hand-built small `GameState` objects exercise each
  rule's thresholds (below, at, above) and provenance; every Insight has
  non-empty `why`; `checklist.rank` ordering and dedup. Fixture-based
  expectations at turn 81: `threat.at_war.4` CRITICAL/ORACLE;
  `threat.active_front.4` WARN/FAIR reporting 6 kills, 3 losses, latest
  an Army Commander at (62,32) on turn 81; `threat.war_intent.1`
  WARN/ORACLE held since turn 72; `threat.targeting.4` with 19 city
  tiles; `threat.targeting.1` with 9; **no** war insight naming player
  7 (Catherine's score of 31 targets player 1); `threat.military_gap.1`
  (11 vs 5); `victory.pursuing.4.CULTURAL` (weight 100);
  `victory.leader.ECONOMIC` for player 2 (72.5 vs 30.0) ADVISE/FAIR;
  `economy.behind.food` WARN (24.0 vs median 59.0); `economy.behind.
  culture` and `.science` INFO; `economy.settlement_slack` "2 of 4";
  `economy.rival_celebration.7` (691/743).
- End-to-end: `run_all(fixture_state)` is non-empty, first item is
  `threat.at_war.4`, ids unique, severities non-increasing, every `why`
  non-empty.
- API: FastAPI `TestClient` — `/api/state` reports turns 82/81,
  `in_progress` true, 8 standings, `ranks["science"] == [7, 7]`;
  `/api/insights` first id `threat.at_war.4`; `/` serves the page;
  `/static/app.js` is served. `Store.publish` reaches a subscriber
  queue.

## 6. Out of scope for v1

- Unit and city map positions beyond what `AI_Targets`/`Historian`
  coordinates give, tech/civic trees, production queues (no data source
  without a mod or save-file parser).
- Any Civ VII mod.
- SQLite persistence and cross-game history (plan B; boundaries above
  make it additive).
- LLM-generated commentary.
- Windows/Linux log paths (use `--logs-dir` for now).
- `Player_WarWeariness.csv` (no turn column) — revisit if a
  who-is-at-war-with-whom table is wanted.

## 7. Tooling

Python 3.12, `uv` for env and run. Runtime dependencies: `fastapi`,
`uvicorn`. Dev: `pytest`, `httpx` (for the test client). Entry point
`civ7-advisor` (`--logs-dir`, `--host`, `--port`, `--poll-interval`)
opens the server on `http://127.0.0.1:8765` and prints the URL.
