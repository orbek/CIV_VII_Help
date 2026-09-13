# Civ Advisor

A second-screen dashboard for single-player Civilization VI and Civilization VII.
It tails the running game's own log files and, every turn, shows where each
rival stands, who is a threat and why, who is emphasizing each strategic
category, how broad outputs compare, how your economy compares, and a ranked
checklist of things to do — each with the evidence behind it. It detects which
game you are playing from the logs themselves, or you can pin one from the
header.

It never writes to the game. Everything runs locally and offline.

## Run

Start Ollama in one terminal (or open the Ollama desktop app):

    ollama serve

The configured default model is already present on the original development
machine. On another machine, install it once with:

    ollama pull gemma4:31b-it-qat

Or use the sparse mixture-of-experts alternative. It is a larger download and
needs more memory than the default (22 GB vs 18 GB), but activates only a
fraction of its weights per token, so it generates faster once loaded:

    ollama pull qwen3.6:35b-a3b

Then start the advisor in another terminal:

    uv sync
    uv run civ-advisor

That uses the default model. To run the advisor against the mixture-of-experts
model you just pulled, name it on the command line:

    uv run civ-advisor --llm-model qwen3.6:35b-a3b

Open http://127.0.0.1:8765 on your second screen and play. The page updates
by itself about a second after the game finishes writing a turn.

### Which game, and where its logs are

`auto` — the default — decides from the games' own gameplay logs. It `stat()`s
only the files each game is known to write, ignoring the engine and diagnostic
logs both games rewrite merely on launch, and picks whichever wrote inside the
last ten minutes. It does not guess: if both games are quiet it says so rather
than choosing the less stale one, and if you pin a game from the header it tells
you when detection disagrees.

| Game | Default log directory |
| --- | --- |
| Civilization VI | `~/Library/Application Support/Sid Meier's Civilization VI/Firaxis Games/Sid Meier's Civilization VI/Logs` |
| Civilization VII | `~/Library/Application Support/Civilization VII/Logs` |

`--logs-dir PATH` overrides one of them and requires `--game`, because a path
does not say which game wrote it. Both directories are opened read-only and
nothing is ever written under them.

### Playing Civilization VI

There is nothing to install, enable or configure in the game. Civ VI writes its
gameplay CSVs on its own — no mod, no FireTuner, no `AppOptions.txt` change.
Start the advisor and play:

    uv run civ-advisor

It picks Civ VI up the first time the game writes a turn. Until then the header
names which game it is waiting on and how long ago each one last wrote. To skip
the wait and pin the game from the start:

    uv run civ-advisor --game civ6

Two things work differently from Civ VII, both because **Civ VI never deletes
its logs**:

- **Every past game is still in the file.** The CSVs are appended to across
  every match you have ever played, so each reader takes only the latest game's
  segment and ignores the turns above it. A file whose boundary cannot be found
  is reported as unreadable rather than quietly mixed into this game.
- **Archiving is a convenience, not the only copy.** Civ VII empties `Logs/` on
  every launch, which is why the advisor mirrors it (see [The game deletes its
  logs](#the-game-deletes-its-logs)). Civ VI does not, so `--no-archive` costs
  you nothing there.

What Civ VI cannot report is stated on the page rather than left blank: it
writes no amenities log, no maintenance breakdown, no record of a signed peace
deal, no combat odds, and nothing saying which victory a rival is pursuing —
`AI_Victories.csv` records era and posture strategies, which is a different
thing. Those panels say the game writes no such log; they never show a zero. In
exchange Civ VI exposes four things Civ VII does not — each AI's combat desire,
its standing diplomatic grievances, and its scored research and civic
preferences. All four are AI-internal, so all four are Oracle.

If `Logs/` holds only engine logs after you have played a turn: check that the
path above is the one your install actually uses (Steam, Epic and the Mac App
Store put user data in different places), and that the turn was played rather
than watched from the main menu. One caveat on "no configuration" — the machine
this was verified on has `EnableDebugMenu 1` in `AppOptions.txt`, and no machine
with it at `0` has been tested. That is the first line to compare if the CSVs
never appear.

## Before you end this turn

The top of the page answers four questions in order.

**What needs attention?** The brief lists the highest-priority decisions, most
severe first, grouped by subject so two warnings about one rival are one entry
rather than two. Every distinct critical alert is shown expanded, however many
there are; only lower-priority items collapse behind a count. Nothing is *only*
in the brief — every original observation is still on its own tab.

**What should I do, where, and why now?** Each decision names a settlement or
frontier, the next action or inspection, and the timing that makes it worth
deciding now. **Why this? · How to do it** opens compact steps beside the
action.

**How do I do it in the game?** The steps come from a small reviewed guide
catalog packaged with the advisor (`civ_advisor/knowledge/civ7/guides.json`) and
each links the article it was written from. The steps say what to look for
rather than naming buttons, because the game's UI changes between updates, and
they never supply a figure — see [Guides and figures](#guides-and-figures).

**What is this based on?** **Evidence** opens a drawer listing every
observation the decision rests on: what it is in words, its value, the turn it
came from, which log file, and what it does *not* establish. Advisor
thresholds, computed comparisons, log rows, figures you supplied, and generated
prose are labelled distinctly and never blended.

**Acknowledge** records that you have seen a decision and drops it from the
brief; **Pin for this session** keeps it in view. Both record your intent —
neither does anything in the game. An acknowledged decision comes back if its
evidence or severity changes.

The header says whether the advisor is connected, when it last got an answer,
which turn the advice was computed on, and which capabilities this game's logs
do not support. "Readable but empty", "nothing recent enough" and "cannot be
read" are reported as what they are, because none of them means the thing being
measured is quiet. It also says which game is being advised on, whether that
was pinned by you or detected from the logs, and — when pinned — whether
detection currently disagrees, so the numbers on screen are never silently
attributed to a game you are not actually looking at.

### Since last turn

The brief carries a **Since last turn** panel: what is newly observed, what got worse or
better, what is no longer reported, and what cannot be compared. It is deliberately
reluctant to claim a trend:

- On the first turn of a game it says there is nothing to compare with, rather than
  showing an empty list that would read as "nothing changed".
- A reload starts a new sitting, so the previous game's turns are not this turn's past.
- If a log a signal depends on became readable or unreadable between the two turns, the
  signal is reported as **not comparable** and says which source moved. A warning that
  vanished with its log has not improved.
- **Resolved** is reserved for a present observation showing the condition has lifted —
  a yield back level with the field, for instance. A signal that merely stopped being
  reported is *no longer reported*, which is a different thing.
- Several rebuilds within one turn replace that turn's record rather than stacking up, so
  a burst of log writes is not history.

### Asking about a decision

Each decision has **Why this?**, **What should I inspect?** and **What would change this
call?**, plus a box to say what you mean to do instead. Every answer is scoped to that one
decision and built from its own facts, candidates and guides.

The structured answer appears immediately. If a local model is running, its prose replaces
it once generated *and* validated: it may only cite ids the decision actually supplied, it
may not contain a URL, and output that is truncated or fenced is rejected. Those checks
catch broken output, not wrong output — which is why generated prose stays labelled as
interpretation while every number, prerequisite and link comes from the structured data.
A slow model delays nothing; the structured answer is already on screen.

What you type in the challenge box is treated as your intention. "I already built a
Monument here" is recorded as a plan, never as an observation that a Monument exists.

### Your own notes

**Acknowledge** and **Pin** are kept in a small local JSON file
(`~/.civ-advisor/<game>/player-context.json` by default; use `--context-file` to move it or
`--no-context-file` to keep nothing). Goals and watchlist entries live there too. It is
written atomically, so a crash cannot leave a half-file, and a damaged one is moved aside
and reported rather than silently replaced.

Entries are filed under the sitting they were made in. When the advisor restarts or the
game is reloaded it **offers** the old entries rather than applying them, saying why it
cannot tell whether this is the same game — the same save seeds do not settle it, because
a save can be branched. Silently carrying an acknowledgement across a reload could hide a
live alert.

### Guides and figures

No figure in a recommendation comes from a wiki or from this advisor's own
guesses. The logs do not record what a building yields, what a settlement can
build, what is unlocked, or what a placement would cost, and no packaged guide
asserts a number verified against an installed ruleset — so every figure comes
from you, for both games today.

Civilization VI ships its compiled ruleset as a queryable database, and the
code to read a building's cost, prerequisites and flat yield from it — labelled
*your installed ruleset*, with the file's timestamp and digest, never a version
number the file does not state — exists and is tested against a real install.
It does not reach a player yet: naming a specific building, or even asking
which options a settlement offers, needs a reviewed Civ VI guide, and Civ VI's
guide catalog has no entries yet (see the multi-game design spec). Until one is
reviewed, Civ VI behaves exactly like Civ VII here. Conditional effects —
policy cards, government and wonder abilities — are not derivable from the
ruleset even once a guide exists, and are never quoted. See
[docs/architecture/adr-002-ruleset-derived-figures.md](docs/architecture/adr-002-ruleset-derived-figures.md)
for where that boundary is and why, and
[docs/architecture/log-capability-matrix.md](docs/architecture/log-capability-matrix.md)
for exactly what is and is not knowable.

So a named building is never presented as an unconditional choice. Instead,
**Refine this recommendation** asks for the few figures only the game can show
you — which culture options a settlement offers, and each one's completion
estimate, culture change, upkeep and local happiness cost. Enter what the
game's own preview says and the advisor compares those options against the
objective you state, shows the arithmetic and the opportunity cost, and names a
choice. Those figures are recorded as *your report*, dated to the turn you read
them, and are discarded if the game is reloaded or that settlement's queue
changes. They never silently override a fresher log row.

Guide links are audited by hand, never during play:

    uv run python scripts/check_guides.py --game civ7

That checks link health only. An HTTP 200 is not a review, and a link-check
date is not the game's version. The script never rewrites the catalog.

The Economy tab also shows what each of your cities is building and, with
Oracle on, what rivals are building.

After each complete turn, the **This turn** tab also receives a cached local
second opinion, explanations for the three highest-ranked insights, and a draft
turn plan. Generation runs in the background; its model, turn, and prompt hash
are displayed with the result. Generated prose is shown beside a decision only
when it was written about that exact decision context — the same turn, the same
evidence mode, the same recommendations and the same figures you had supplied.
If you change any of those while a generation is running, the finished prose
appears as dated history instead, never as an explanation of what is now on
screen. Fair mode gets its own generation from a fair prompt rather than hiding
every result that ever read an intercept.

Options: `--game auto|civ6|civ7` (default `auto`: the advisor detects which game
is being played from the games' own logs each poll, and you can override it from
the header at any time), `--logs-dir PATH` (requires `--game`, because a log
directory belongs to one game and the path does not say which), `--port`,
`--host`, `--poll-interval`, `--llm-model MODEL`, `--llm-timeout SECONDS`,
`--no-llm`, `--context-file PATH`, and `--no-context-file`.

Ollama commentary is optional. The advisor checks only the loopback service at
`127.0.0.1:11434`, rejects `:cloud` models, and never sends raw logs to the
model. If Ollama is stopped or the model is missing, one quiet notice replaces
the commentary while every deterministic panel keeps working. Any installed
local model can be used instead of the default by passing it explicitly:

    uv run civ-advisor --llm-model qwen3.6:35b-a3b

or, for a much smaller one on a constrained machine:

    uv run civ-advisor --llm-model llama3.2:3b

The choice of model changes only the generated prose. Every figure, threshold,
comparison and link on the page is computed from the logs, so a different model
cannot change what the advisor asserts — and the model that produced a piece of
prose is displayed with it.

## Fair vs Oracle

Advice built only from things you could see in-game is **Fair**. Advice that
uses the AI's internal logs — its war-intent scores, its target lists, and its
strategic focus weights in Civilization VII; its combat desire, its standing
diplomatic grievances, and its scored research and civic preferences in
Civilization VI — is **Oracle**, drawn over a faint diagonal
hatch and badged "intercept". Combat desire in particular is read relative to
the same turn's other rivals and to the rival's own earlier reading; the game
publishes no scale for it, so it is never a calibrated danger level, however
it is badged. Untick **Oracle** in the header to see whether
the fair evidence alone would have told you the same thing. That comparison is
the point: it shows you where your read of the game was right and where it
wasn't. The toggle hides Oracle table columns too, not just the cards — and with Oracle
off the AI-internal fields are absent from the server's response, not merely
blanked in the browser. Switching it off repaints immediately, so an in-flight
response cannot put intercepted content back afterwards.

The fifth tab, **Intel**, plots a compact, city-focused tactical intercept and lists gossip,
diplomacy, fights and deals newest first. The map is deliberately limited to
known human city-area target tiles and recent AI-planned unit positions near
them; a contact table retains the closest off-map positions. It is not terrain
or fog of war. Gossip is Fair because the game shows it to you. For
party-bearing events, events involving you are Fair and events between other
players are Oracle. The entire tactical payload is withheld server-side when
Oracle is off.

## The game deletes its logs

Civ VII empties its `Logs/` folder every time it starts and rewrites it from
the turn your save is on. The advisor therefore mirrors every log file in the
folder to `~/.civ-advisor/<game>/archive/<save-key>/<session>/` on every
rebuild. Turn it off with `--no-archive`, point it elsewhere with
`--archive-dir PATH`, and list what is kept with `civ-advisor archive list`.
Nothing is ever written under the game's own folders.

`--archive-dir` means two different things depending on which subcommand it is
given to, and that difference is deliberate rather than an oversight, so it is
spelled out here rather than left implicit: for `civ-advisor` itself it names
one destination — every game archives directly under that path, no `<game>`
segment appended. For `civ-advisor archive list` it instead names the BASE that
holds every game's own subdirectory, because listing has to look across every
game to show anything. If you pass the same path to both, `civ-advisor`'s
own run writes flat into it while `list` expects a `<game>/archive/...` layout
beneath it — pass `list` the parent of what you gave the running advisor, not
the same path, unless you intend one game's archive to be treated as the base.

Storage is per game: Civilization VI and Civilization VII keep separate archives
and separate goals, acknowledgements and watchlists. An acknowledgement made in
one game is never offered in the other.

**Upgrading from an earlier version?** Your existing archive and notes are still
at `~/.civ7-advisor/`. Nothing has been moved or deleted. `civ-advisor archive
list` still shows them, labelled `pre-2b`, and the advisor prints the one-line
`mv` that would adopt them the first time it starts without them.

## What is verified, and what isn't

The reading of the logs is verified: every number quoted in an insight's
evidence — unit counts, yields, scores, turn numbers — is taken straight from
the game's own files, and both real-session fixtures exercise the parsers.
Mechanics-bearing recommendations were reviewed against the current official
game guide; stale Legacy Path and fixed build-order claims were removed. The
remaining numeric cutoffs are explicitly advisor triage policy, not game
rules. Only two archived games exist today, so those cutoffs have not been
retuned; treat recommendations as evidence-backed prompts for judgment rather
than guaranteed optimal moves.

## Tuning

Every threshold is a named constant at the top of its advisor module:
`civ_advisor/advisors/threat.py`, `tactical.py`, `victory.py`, `economy.py`,
and `production.py`. Change a number, restart, done.

These thresholds are advisor triage policy, not Civ VII rules. Audit their
distribution once per locally archived game (using its most advanced session)
with:

    uv run python scripts/calibrate_advisor.py

The current mechanics review and correction rationale are in
`docs/research/2026-09-07-v2-grounded-strategy-findings.md`.

## Tests

    uv run pytest

The fixtures in `tests/fixtures/logs_82turns/` and `tests/fixtures/logs_v2/`
are snapshots of real 82-turn and 100-turn sessions, and
`tests/fixtures/logs_civ6/` is a real turn-53 Civ VI capture, so the whole
pipeline is exercised against genuine output from both games. Try the dashboard
against either without the game running:

    uv run civ-advisor --logs-dir tests/fixtures/logs_v2 --game civ7 --no-archive
    uv run civ-advisor --logs-dir tests/fixtures/logs_civ6 --game civ6 --no-archive

The dashboard's own rules — which response may paint, how coverage is worded,
how decisions group, when generated prose may be shown — are executed under
`node` by `tests/test_web_briefing.py`, so they need no browser.

A separate opt-in suite drives a real page for the things source assertions
cannot establish: what fits on screen, what a keyboard can reach, whether a
citation opens the right observation, and whether hidden data can come back.

    uv sync --group browser
    uv run playwright install chromium
    uv run pytest tests/browser

See [tests/browser/README.md](tests/browser/README.md). It is excluded from the
default run so that stays offline and fast.

## Design

See `docs/superpowers/specs/2026-09-07-civ7-turn-advisor-design.md` for v1 and
`docs/superpowers/specs/2026-09-07-civ7-advisor-v2-design.md` for this feature.
