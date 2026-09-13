# Live suite

Opt-in, and not part of `uv run pytest` -- `addopts` in `pyproject.toml` ignores this
directory, because the default run must stay offline. These tests talk to a real,
running Civilization VI over its tuner socket (127.0.0.1:4318), so they need a match
loaded and the tuner turned on.

## Setup (once per game session)

1. Open `AppOptions.txt` in Civilization VI's own configuration directory and, under
   `[Debug]`, set:

   ```
   EnableTuner 1
   ```

2. Restart the game and load into a match.

The advisor will never make that change for you: `AppOptions.txt` lives inside the
game's own directory, and this program is read-only with respect to both games'
directories -- see the "Playing Civilization VI" section of the top-level README for
what turning it on unlocks and what it costs.

## Running

```bash
uv run pytest tests/live -p no:cacheprovider
```

With no game up, or the tuner off, every test in the module is skipped (not failed):
`conftest.py` checks the socket before anything else runs.

## What is checked here and not elsewhere

Every other test that touches the tuner protocol runs against a fixture or a fake
socket, because the default suite must stay offline. Those checks parse fixed,
known-good replies; they cannot show that a real, currently-installed Civilization VI
answers each catalog query the way this code expects. That is what this suite is for --
and because whoever runs it has their own cities, their own maintenance bill and their
own build queues, each check here asserts a SHAPE the reply must have (a maintenance
breakdown that sums to its own total; a non-negative turn estimate on every build
option), never a specific value.
