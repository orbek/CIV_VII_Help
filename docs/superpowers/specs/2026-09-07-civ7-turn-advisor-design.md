# Civ VII Turn Advisor — Design

**Date:** 2026-09-07
**Status:** Approved for planning
**Scope:** Version 1

## 1. Purpose

A second-screen web dashboard that watches a running single-player game of
Sid Meier's Civilization VII, reads the game's own per-turn log files, and
each turn shows (a) where every rival stands, (b) which rivals are a threat
and why, (c) who is winning the victory race, (d) how the player's economy
compares to the field, and (e) a ranked list of recommended actions for
the turn — each with the evidence that produced it.

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

Files used in v1 (all verified against a live 82-turn game on this
machine):

| File | Rows | Used for |
|---|---|---|
| `Player_Stats.csv` | one per (turn, player) | cities, towns, settlement cap, population, techs, land/naval units, tiles, gold balance, all yields |
| `Game_PlayerScores.csv` | one per (turn, player) | score |
| `Player_Treasury.csv` | one per (turn, player) | gold balance, maintenance breakdown, gold yield |
| `Player_Happiness.csv` | one per (turn, player) | happiness |
| `Player_WarWeariness.csv` | one per (turn, player) | war weariness |
| `AI_Victories.csv` | one per (turn, AI player) | victory strategy being followed and progress % |
| `AI_DiplomaticActions.csv` | one per (turn, AI player, action) | scored diplomatic intents incl. `DECLARE_WAR` against a target |
| `AI_Targets.csv` | one per (turn, AI player, target) | target type, owner and `X:Y` map location |
| `Historian.csv` | one per event | discoveries, unit kills, etc. with turn, X/Y, player, opponent |

Player identity: player `0` is the human (never appears in `AI_*` files).
Players with a `LOC_LEADER_*_NAME` owner in `AI_Victories.csv` are rival
civilizations; players whose owner is `LOC_CIVILIZATION_INDEPENDENT_NAME`
are independent peoples and are excluded from rival rankings.

### 2.1 Verified hazards the ingest layer must handle

1. **Ragged header in `Player_Stats.csv`.** The header has 22 names; data
   rows have 25 columns. `TILES:`, `BALANCE:`, `YIELDS:` and `BY TYPE:`
   are group labels, not columns. The parser maps columns **by
   position** using a mapping pinned against known-good values from the
   live game, and raises on any row whose column count differs from the
   pinned count. It never trusts the header for this file.
2. **Partial turns.** Rows for turn *N* arrive one player at a time.
   `Player_Stats.csv` may be at turn 82 for player 0 while `AI_*` files
   are still on turn 80–81. A turn is treated as complete only once any
   row for the *following* turn exists in `Player_Stats.csv`, so
   `complete_through_turn = latest_turn - 1`. This is the state at the
   start of the human's current turn, which is exactly what the advice
   should be based on. The UI shows the in-progress turn as such.
   Checking "every rival has a row" does **not** work, because
   eliminated players simply stop appearing (Napoleon, player 3, last
   appears at turn 59 in the live game).
2a. **Eliminated players.** A rival whose last `Player_Stats` row is
   older than `complete_through_turn` is marked `alive = False` and is
   excluded from rankings and threat analysis, but kept in the player
   list so historical events still resolve to a name.
2b. **Three row shapes in `AI_DiplomaticActions.csv`.** The third
   column is one of: `DIPLOMACY_ACTION_*` (a scored candidate action),
   `LOC_DIPLOMACY_ACTION_*_NAME` (same meaning, localized-key variant),
   or `ACTION DIPLOMACY_ACTION_* ` with a fifth column `TOKENS n` (the
   action was **executed**). The reader normalizes all three to one
   `DiplomaticIntent` row with a `kind: SCORED | EXECUTED` field and a
   canonical action name. A target of `-1` means unknown/none and is
   never treated as the human. In the live game players 1 and 4 hold
   sustained `DECLARE_WAR` scores of ~202–204 against player 0 for
   turns 77–81, and player 4 has an `EXECUTED` `DECLARE_WAR` at turn 80.
3. **Multi-game files.** Because logs are never truncated, a file
   contains every game played since install. A new game is detected
   when the turn number in a file drops below the previous row's turn.
   Only the most recent game segment is exposed.
4. **Lag between files.** Different files reach a given turn at
   different times. The state layer joins on turn number, tolerating
   missing rows for the newest turns rather than assuming alignment.
5. **Localized keys.** Leader names arrive as `LOC_LEADER_CONFUCIUS_NAME`.
   A small static dictionary maps known keys to display names; unknown
   keys fall back to a cleaned-up form of the key.

## 3. Architecture

Single Python process, run with `uv run civ7-advisor`, no build step,
no network access required.

```
Civ VII Logs/*.csv
        │  watchdog file events, debounced ~500 ms
        ▼
  civ7_advisor/ingest/     one reader per file → typed row dataclasses
        ▼
  civ7_advisor/state/      GameState snapshot (current game only)
        ▼
  civ7_advisor/advisors/   pure functions GameState → list[Insight]
        ▼
  civ7_advisor/api/        FastAPI: /api/state, /api/insights, /events (SSE)
        ▼
  civ7_advisor/web/        static index.html + style.css + app.js
```

Dependencies point strictly downward. `advisors/` imports nothing from
`ingest/` and knows no file paths. `api/` is the only layer that knows
about HTTP. This is what keeps the planned **B evolution** cheap: SQLite
persistence replaces the in-memory store inside `state/`; a separate
React frontend would consume the same `/api` routes.

### 3.1 `ingest/`

- `readers.py` — one function per log file. Each takes a path, returns
  a list of typed rows for the **most recent game segment only** (see
  hazard 3). All readers are pure: path in, rows out.
- `columns.py` — the pinned positional column map for
  `Player_Stats.csv` and the expected column count.
- `watcher.py` — `watchdog` observer on the `Logs/` directory, debounced,
  calling a single `on_change()` callback. Only this module knows the
  directory location, which comes from a `--logs-dir` flag defaulting to
  the macOS path above.

### 3.2 `state/`

- `models.py` — dataclasses: `PlayerTurn` (all per-turn stats for one
  player), `Player` (id, display name, kind: `HUMAN | RIVAL |
  INDEPENDENT`, `alive: bool`, `last_seen_turn`), `VictoryStatus`,
  `DiplomaticIntent` (turn, actor, action, target, kind:
  `SCORED | EXECUTED`, score), `Target`,
  `HistorianEvent`, and `GameState` holding all of these plus
  `latest_turn`, `complete_through_turn`, and a `history` of
  `PlayerTurn` by turn for trend computation.
- `build.py` — `build_state(rows...) -> GameState`. Joins rows across
  files by turn and player, classifies players, computes
  `complete_through_turn`.
- `store.py` — holds the current `GameState`, rebuilds on `on_change()`,
  and notifies subscribers (the SSE endpoint). In v1 the store is
  in-memory; its interface (`get()`, `subscribe()`) is what SQLite would
  later implement.

### 3.3 `advisors/`

```python
class Provenance(Enum):
    FAIR = "fair"      # derivable from what the player can see in-game
    ORACLE = "oracle"  # uses AI-internal data the game hides

class Severity(Enum):
    INFO, ADVISE, WARN, CRITICAL

@dataclass
class Insight:
    id: str            # stable key, e.g. "threat.war_intent.7"
    advisor: str       # "threat" | "victory" | "economy"
    severity: Severity
    provenance: Provenance
    title: str
    recommendation: str
    why: str           # evidence, plain language, with numbers
    turn: int          # complete_through_turn it was computed on
    subject_player: int | None
```

Each advisor module exposes `advise(state: GameState) -> list[Insight]`.
Tunable thresholds are module-level named constants at the top of each
file — plain Python, no config DSL.

- **`threat.py`** — For each rival: war-intent score against player 0
  from `AI_DiplomaticActions` (ORACLE); military ratio rival/human from
  land + naval unit counts (FAIR); trend of both over the last N turns.
  Emits CRITICAL when an `EXECUTED` `DECLARE_WAR` against player 0 is
  seen (you are at war — ORACLE only in timing, since the game tells you
  too); WARN when a `SCORED` war intent exceeds a threshold or is
  climbing fast, with an estimated lead time from the slope; and FAIR
  advisories when a rival's army is growing faster than yours regardless
  of stated intent.
- **`victory.py`** — From `AI_Victories`: each rival's strategy and
  progress % (ORACLE), with rate of change so an accelerating 40%
  outranks a stalled 55%. From scores and stats (FAIR): who leads in
  score, science, culture. Emits "race or deny" recommendations.
- **`economy.py`** — Human yields vs median and leader of rivals
  (FAIR): science, culture, gold, production, food, happiness,
  settlement cap usage. Emits the single stat furthest behind pace,
  with the lever to pull (settle, build, trade, etc.).
- **`checklist.py`** — Takes the merged `list[Insight]` from the three
  above and returns them ordered by severity, then recency of trigger,
  deduplicated by `id`. No data access of its own.

### 3.4 `api/`

- `GET /api/state` — JSON of the current `GameState` (players, latest
  turn, complete turn, current-turn stats).
- `GET /api/insights` — JSON `list[Insight]`, already ranked.
- `GET /events` — SSE stream; emits `{"type": "state_changed", "turn":
  N}` whenever the store rebuilds. The browser then refetches.
- `GET /` — serves `web/index.html`; static files under `/static`.

### 3.5 `web/`

One page. Header strip always visible: current turn (with "in
progress" marker when `latest_turn > complete_through_turn`), the
human's score rank among rivals, and the single highest-severity
insight. Four tabs:

1. **Checklist** — ranked insight cards.
2. **Threats** — rival table (name, war score, military ratio, trend
   arrows) plus threat insights.
3. **Victory** — rival table (strategy, progress %, delta) plus
   victory insights.
4. **Economy** — human vs field yield comparison plus economy insights.

Every insight card shows `title`, `recommendation`, and `why` inline.
ORACLE insights are rendered with a distinct border and an "Oracle"
badge; a header toggle **hides all ORACLE insights** so the player can
see whether fair-play evidence alone reaches the same conclusion.

Vanilla JS, no framework, no bundler. Dark theme.

## 4. Error handling

- A malformed or unexpected row in any log file is logged with file,
  line number and reason, and that **file's** rows are dropped for
  that rebuild; other files still produce state. The UI shows a
  warning chip naming the degraded file.
- `Player_Stats.csv` column-count mismatch is treated as fatal for that
  file (never guessed), with a clear message telling the user the game
  version may have changed the log format.
- If the `Logs/` directory does not exist, the process exits with a
  message showing the path it looked for and the `--logs-dir` flag.
- SSE clients that disconnect are dropped silently; the page
  reconnects automatically.

## 5. Testing

- `tests/fixtures/logs_82turns/` — a snapshot of the real `Logs/` CSVs
  from the live game on this machine (only the files listed in §2).
  This is the primary fixture; it contains the ragged header, the
  partial turn 82, and real AI war-intent rows.
- `ingest/` tests: each reader parses the fixture without error, row
  counts and spot-checked values match hand-verified numbers (e.g.
  turn 82 player 0 science yield = 15.0, gold balance = 136.0), and a
  synthetic two-game file yields only the second game.
- `ingest/` also: `AI_DiplomaticActions` reader normalizes all three
  row shapes; the turn-80 player-4 `ACTION DIPLOMACY_ACTION_DECLARE_WAR`
  row becomes `kind == EXECUTED`; a target of `-1` is preserved as
  `None`.
- `state/` tests: `build_state` on the fixture reports
  `latest_turn == 82` and `complete_through_turn == 81`; classifies
  players 1–7 as RIVAL and 0 as HUMAN; player 3 (Napoleon) has
  `alive == False` with `last_seen_turn == 59`; independents and dead
  rivals excluded from rankings.
- `advisors/` tests: hand-built small `GameState` objects exercise each
  rule's thresholds (below, at, above); every Insight has non-empty
  `why`; `checklist` ordering and dedup.
- End-to-end: fixture → state → insights produces a CRITICAL threat
  insight for player 4 (Rizal, executed `DECLARE_WAR` on player 0 at
  turn 80), a WARN threat insight for player 1 (Ibn Battuta, sustained
  war score ≈202 against player 0 through turn 81), **no** war insight
  naming player 7 (Catherine's score of 31 targets player 1, not the
  human), and a non-empty ranked checklist.
- API smoke test with FastAPI's test client for the three JSON routes.

## 6. Out of scope for v1

- Unit and city map positions, tech/civic trees, production queues
  (no data source without a mod or save-file parser).
- Any Civ VII mod.
- SQLite persistence and cross-game history (plan B; boundaries above
  make it additive).
- LLM-generated commentary.
- Windows/Linux log paths (add via `--logs-dir` for now).

## 7. Tooling

Python 3.12, `uv` for env and run, `fastapi` + `uvicorn` + `watchdog`
+ `sse-starlette`, `pytest`. Entry point `civ7-advisor` opens the
server on `http://127.0.0.1:8765` and prints the URL.
