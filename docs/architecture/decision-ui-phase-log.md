# Decision UI delivery log

Verification and remaining limitations for each completed phase of
[the companion decision UI plan](../superpowers/plans/2026-09-08-civ7-companion-decision-ui.md).
Nothing is recorded here on the strength of code inspection alone: each claim names the
check that produced it.

## Phase 1 — Consistent state, coverage, and status (2026-09-08)

### What changed

- `Store.rebuild` now publishes one immutable `Snapshot` (`civ7_advisor/store.py`) carrying
  the state, ranked insights, per-domain coverage, session/epoch identity and a monotonic
  revision. `Store.state` and `Store.insights` remain readable and are derived from that
  snapshot, so no request can straddle a rebuild.
- Session identity is computed on every rebuild whether or not archiving is enabled. A new
  epoch begins on a log wipe, a seed change, or a turn that moves backwards; the reason is
  published as `epoch_reason`. Ambiguity resolves towards a new epoch.
- `GET /api/briefing?oracle=` serves status, state, insights, intel, tactical and
  commentary from a single revision. `/api/status` is the same header data alone. The
  legacy endpoints remain and now take the same `oracle` flag.
- Evidence filtering moved to the server (`advisors.base.visible`). With `oracle=0` the
  Oracle insights, Oracle intel events, the AI-internal `RivalThreat` fields, rival victory
  strategies and the whole tactical block are absent from the response rather than blanked
  by the browser. The prompt builder filters too, so fair mode has its own generation
  instead of hiding every result that ever saw an intercept.
- The browser makes one request, numbers it, aborts the superseded one, and refuses any
  reply that is out of sequence or carries an older revision within the same session.
  Switching Oracle off repaints before fetching, so intercepts disappear immediately.
- The header reports connection state, time since the last successful update, the analysis
  turn, and per-capability coverage. `empty`, `stale`, `partial` and `unavailable` are
  worded as what they are; an optional log the game never wrote produces one quiet line
  naming the disabled capability, not a warning.
- Tactical city-area tiles and attack goals carry the turn they were observed on. An
  attack objective older than `GOAL_FRESH_TURNS` is reported as a dated last-known
  objective at ADVISE, not as an immediate one at CRITICAL — and its absence is explicitly
  not treated as safety.
- Commentary distinguishes `queued`, `generating`, `error` and `ready`, and every
  generation carries a `CommentaryIdentity` (session, epoch, evidence mode, snapshot
  revision, turn, contributing insight ids, plus decision/context/catalog revisions
  initialised for phases 2–3). A replaced pending job no longer leaves a cached
  placeholder. Earlier prose is offered only as dated history within the same session and
  evidence mode.

### Exit checks and how each was verified

| Exit check | Verified by | Result |
| --- | --- | --- |
| A delayed Oracle-on response cannot restore hidden data | `tests/test_web_briefing.py::test_a_delayed_oracle_on_reply_cannot_restore_data_the_player_switched_off` — the plan's reproduction, executed under `node` against `web/briefing.js` | Pass: the stale reply is refused on sequence, and `seen` is already false before any reply lands |
| Individual sources paused or failing report honest coverage | `tests/test_store.py::test_coverage_tells_empty_stale_and_unreadable_apart` (empty, stale, malformed, absent, partial in one rebuild) and `::test_a_log_written_once_per_save_is_not_reported_as_stale` | Pass |
| Interleaved rebuilds and requests see one revision | `tests/test_store.py::test_revision_is_monotonic_and_each_snapshot_is_internally_coherent`; `tests/test_api.py::test_briefing_serves_every_section_from_one_revision` | Pass |
| A reload or save reset changes the epoch | `tests/test_store.py::test_a_log_wipe_and_reload_start_a_new_epoch`, `::test_a_turn_that_moves_backwards_starts_a_new_epoch`, `::test_loading_a_different_save_starts_a_new_epoch` | Pass |
| A→B→C→B pending jobs leave no permanent spinner | `tests/test_llm.py::test_a_replaced_pending_prompt_can_still_be_generated_later` | Pass — this reproduced the real defect: B's cached placeholder previously blocked it forever |
| Fair mode is not permanently empty | `tests/test_llm.py::test_fair_mode_generates_its_own_commentary_instead_of_hiding_everything`; `tests/test_api.py::test_briefing_in_fair_mode_omits_intercepted_evidence_rather_than_blanking_it` | Pass |

Suite: `uv run pytest` — 304 passed. `node --check` on `web/app.js` and `web/briefing.js`.
`git diff --check` clean. Manual end-to-end run against `tests/fixtures/logs_v2` with
`--no-archive --no-llm`: `/api/status` reports session, epoch, revision, seeds and full
coverage; `/api/briefing?oracle=1` returns 27 insights and `?oracle=0` returns 15 with
`hidden_insights: 12`, no `war_score` field on any threat row, and tactical withheld.

### Remaining limitations

- **No end-to-end browser test yet.** The response and coverage rules are executed for
  real under `node`, but that no oracle-derived *region* renders when `seen()` is false is
  currently held by code structure plus the server-side filtering tests, not by driving a
  page. The plan puts the Playwright suite and its dev-only dependency setup in Phase 4;
  the delayed-response and mode-switch scenarios should be re-run there against the DOM.
- **Focus restoration is untested against a real DOM** for the same reason. It also only
  restores elements that carry an `id` or `data-focus-key`; controls added in Phase 4 must
  set one.
- **`GameCore.log` is read twice per rebuild** — once by `read_player_identities` and once
  by `archive.game_key` for seed-change detection. Correct, but wasteful; folding the seeds
  into `RawLogs` would remove the second read.
- **Fair-mode commentary is generated on demand**, so the first fair request after a
  rebuild reports `queued`/`generating` rather than being ready. Oracle mode is scheduled
  eagerly. Phase 6 revisits prompt and cache identity per mode.
- **`stale` remains a judgement call for episodic logs.** Combat or gossip having no recent
  rows is reported with its date and an explicit "dated, not quiet" note, but it is still
  listed among coverage gaps; if that proves noisy in play, episodic domains may need their
  own wording rather than a shared status.
- Session identity is per process. Nothing is persisted yet, so acknowledgements and
  epochs do not survive a restart of the advisor — Phase 6 owns the local store.
