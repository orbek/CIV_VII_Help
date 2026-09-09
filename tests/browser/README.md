# Browser suite

Dev-only. These tests drive a real page with Playwright, so they need a browser on disk
and they start a server. They are **not** part of `uv run pytest` — `addopts` in
`pyproject.toml` ignores this directory — because the default run must stay offline, fast
and dependency-light.

## Setup (once)

```bash
uv sync --group browser
uv run playwright install chromium
```

## Running

```bash
uv run pytest tests/browser
```

Add `--headed` to watch it, or `-k <name>` for one check.

## What is checked here and not elsewhere

`tests/test_web_briefing.py` executes the dashboard's *rules* under node — which reply may
paint, how coverage is worded, how decisions group, when generated prose may be shown. That
is fast and needs no browser, but it cannot establish that the page actually calls those
rules, that a control is reachable by keyboard, that the first decision fits on screen, or
that focus comes back when a dialog closes. Those are the checks in here.

Two of them exist specifically because a source-string assertion would have passed while
the behaviour was broken:

- `test_a_delayed_oracle_on_reply_cannot_repaint_intercepts` holds an Oracle-on response,
  switches Oracle off, then releases it — the defect the plan opens with.
- `test_five_critical_decisions_all_render_without_an_overflow_click` uses a fixture with
  five real war declarations, rather than injecting entries into the page, so it exercises
  the render path a player would hit.
