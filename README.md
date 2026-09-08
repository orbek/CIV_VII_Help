# Civ VII Turn Advisor

A second-screen dashboard for single-player Civilization VII. It tails the
game's own log files (`~/Library/Application Support/Civilization VII/Logs`)
and, every turn, shows where each rival stands, who is a threat and why, who
is emphasizing each strategic category, how broad outputs compare, how your economy compares, and a
ranked checklist of things to do — each with the evidence behind it.

It never writes to the game. Everything runs locally and offline.

## Run

Start Ollama in one terminal (or open the Ollama desktop app):

    ollama serve

The configured default model is already present on the original development
machine. On another machine, install it once with:

    ollama pull gemma4:31b-it-qat

Then start the advisor in another terminal:

    uv sync
    uv run civ7-advisor

Open http://127.0.0.1:8765 on your second screen and play. The page updates
by itself about a second after the game finishes writing a turn.

The Economy tab also shows what each of your cities is building and, with
Oracle on, what rivals are building.

After each complete turn, the **This turn** tab also receives a cached local
second opinion, explanations for the three highest-ranked insights, and a draft
turn plan. Generation runs in the background; its model, turn, and prompt hash
are displayed with the result. Because the v2 prompt includes intercepted
tactical evidence, this commentary is hidden when Oracle is off.

Options: `--logs-dir PATH` (if your logs live elsewhere), `--port`, `--host`,
`--poll-interval`, `--llm-model MODEL`, and `--no-llm`.

Ollama commentary is optional. The advisor checks only the loopback service at
`127.0.0.1:11434`, rejects `:cloud` models, and never sends raw logs to the
model. If Ollama is stopped or the model is missing, one quiet notice replaces
the commentary while every deterministic panel keeps working. To use a smaller
installed local model, pass it explicitly, for example:

    uv run civ7-advisor --llm-model llama3.2:3b

## Fair vs Oracle

Advice built only from things you could see in-game is **Fair**. Advice that
uses the AI's internal logs — its war-intent scores, its target lists, and its
strategic focus weights — is **Oracle**, drawn over a faint diagonal
hatch and badged "intercept". Untick **Oracle** in the header to see whether
the fair evidence alone would have told you the same thing. That comparison is
the point: it shows you where your read of the game was right and where it
wasn't. The toggle hides Oracle table columns too, not just the cards.

The fifth tab, **Intel**, plots a compact tactical intercept and lists gossip,
diplomacy, fights and deals newest first. The map is deliberately limited to
known human city tiles and recent AI-planned unit positions; it is not terrain
or fog of war. Gossip is Fair because the game shows it to you. For
party-bearing events, events involving you are Fair and events between other
players are Oracle. The entire tactical payload is withheld server-side when
Oracle is off.

## The game deletes its logs

Civ VII empties its `Logs/` folder every time it starts and rewrites it from
the turn your save is on. The advisor therefore mirrors every log file in the
folder to `~/.civ7-advisor/archive/<game>/<session>/` on every rebuild. Turn it
off with `--no-archive`, point it elsewhere with `--archive-dir PATH`, and list
what is kept with `civ7-advisor archive list`. Nothing is ever written under
the game's own folders.

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
`civ7_advisor/advisors/threat.py`, `tactical.py`, `victory.py`, `economy.py`,
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
are snapshots of real 82-turn and 100-turn sessions, so the whole pipeline is
exercised against genuine Civ VII output. Try the dashboard against the newer
fixture without the game running:

    uv run civ7-advisor --logs-dir tests/fixtures/logs_v2 --no-archive

## Design

See `docs/superpowers/specs/2026-09-07-civ7-turn-advisor-design.md` for v1 and
`docs/superpowers/specs/2026-09-07-civ7-advisor-v2-design.md` for this feature.
