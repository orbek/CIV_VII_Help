# Civ VII Turn Advisor

A second-screen dashboard for single-player Civilization VII. It tails the
game's own log files (`~/Library/Application Support/Civilization VII/Logs`)
and, every turn, shows where each rival stands, who is a threat and why, who
is pursuing and leading each legacy path, how your economy compares, and a
ranked checklist of things to do — each with the evidence behind it.

It never writes to the game. Everything runs locally and offline.

## Run

    uv sync
    uv run civ7-advisor

Open http://127.0.0.1:8765 on your second screen and play. The page updates
by itself about a second after the game finishes writing a turn.

Options: `--logs-dir PATH` (if your logs live elsewhere), `--port`, `--host`,
`--poll-interval`.

## Fair vs Oracle

Advice built only from things you could see in-game is **Fair**. Advice that
uses the AI's internal logs — its war-intent scores, its target lists, the
legacy path it has committed to — is **Oracle**, drawn with a dashed border
and a badge. Untick **Oracle** in the header to see whether the fair evidence
alone would have told you the same thing. That comparison is the point: it
shows you where your read of the game was right and where it wasn't.

## What is verified, and what isn't

The reading of the logs is verified: every number quoted in an insight's
evidence — unit counts, yields, scores, turn numbers — is taken straight from
the game's own files, and the parsers are tested against a snapshot of a real
82-turn game. The advice built on top of those numbers is not. The
recommendations that name particular buildings and mechanics, and the
threshold values that decide when an insight fires, come from the model's
understanding of Civ VII rather than from checked sources; a research pass to
confirm them against current game mechanics is queued as separate work. Trust
the evidence, and treat the recommendation as a first draft.

## Tuning

Every threshold is a named constant at the top of its advisor module:
`civ7_advisor/advisors/threat.py`, `victory.py`, `economy.py`. Change a
number, restart, done.

## Tests

    uv run pytest

The test fixture in `tests/fixtures/logs_82turns/` is a snapshot of a real
82-turn game, so the whole pipeline is exercised against genuine Civ VII
output. Try the dashboard against it without the game running:

    uv run civ7-advisor --logs-dir tests/fixtures/logs_82turns

## Design

See `docs/superpowers/specs/2026-09-07-civ7-turn-advisor-design.md`.
