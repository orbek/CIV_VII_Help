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

## Phase 2 — Structured evidence and reviewed guide catalog (2026-09-08)

### What changed

- `decisions/models.py` implements the section 3 contracts — `EvidenceFact`,
  `ActionCandidate`, `DecisionCard`, `PlayerReport`, `PlayerContext` — with defaults so
  advisors migrate one at a time. Two invariants are enforced in the types rather than by
  convention: a derived fact must cite what it came from, and a candidate cannot be
  `READY` while any prerequisite is unmet or unknown.
- `decisions/evidence.py` builds facts from the parsed rows with typed source keys
  (`("Player_Stats.csv", 99, 0)`), never by scraping an insight's `why` prose. Oracle
  provenance propagates transitively through derivations, so a comparison resting on an
  intercepted fact is itself intercepted.
- `knowledge/catalog.py` + `guides.json` package five reviewed references, loaded offline
  via `importlib.resources`. Link health, editorial review and ruleset compatibility are
  three separate fields. Validation rejects non-Civ-VII articles, unknown publishers,
  non-https URLs, instructions on an unreviewed entry, and any exact effect without a
  ruleset it was verified against.
- `scripts/check_guides.py` is the online audit. It never rewrites the catalog and
  distinguishes "blocked" from "gone".
- `GameState.identities` carries civilization and leader per player explicitly.
- `docs/architecture/log-capability-matrix.md` records what the logs can and cannot say.

### Findings from the actual audit

Three of these changed what the code does, so they are recorded rather than summarised:

1. **The build queue is not a census.** In the real 100-turn fixture the human has six
   settlements and exactly one has a queue row. `settlement_coverage_fact` now states
   "1 of 6 settlements have a logged queue; 5 are unobserved. Their queues are unknown,
   not idle." Nothing may be said about the other five.
2. **The official 2K settlement guide is reachable**, unlike the plan's earlier attempt.
   Reading it supplied the inspection workflow from the publisher's own documentation:
   the production menu shows build time, base yields, warehouse improvement counts and
   best available adjacencies; predicted yields moved to the *placement* context, where
   hovering a legal tile previews the settlement-yield change, overbuilding effects and
   maintenance, with an expanded before/after breakdown; growth events present the
   improvement-or-specialist choice with the same tools, and urban tiles show specialist
   capacity. This is version-scoped to Update 1.2.5 and later — the article says the older
   presentation remains available as an option — so the entry carries
   `supported_rulesets: ["update-1.2.5-or-later"]` and the steps say what to look for
   rather than naming buttons.
3. **Fandom returns HTTP 403 to automated requests.** The audit's first version reported
   four live articles as "gone". Acting on that would have dropped working guidance, so
   `blocked` is now a distinct status that says the publisher refused *this client* and
   the URL must be checked by hand.

The Age question resolved better than expected: `Historian.csv` has an `Age` column, and
all 184 events in the fixture are `AGE_ANTIQUITY` across turns 3–100. That is dated
evidence, so `age_fact` reports it with its turn and an explicit note that it does not
prove the Age is unchanged; two Ages on one turn make the current Age unreadable and it
says so. Unlocks, available builds, existing buildings, policies, specialist slots, tile
adjacency and per-city upkeep have **no source at all** and therefore no parser.

### Exit checks and how each was verified

| Exit check | Verified by | Result |
| --- | --- | --- |
| Each pilot signal resolves its evidence ids | `tests/test_evidence.py` — comparison, queue, coverage, net gold, happiness, completions, Age, identity, defence | Pass |
| Derived comparisons cite every observation and the rule threshold | `::test_a_derived_comparison_cites_every_row_and_the_rule_it_applied` | Pass |
| Malformed or non-Civ-VII entries are rejected | `tests/test_guide_catalog.py::test_a_non_civ_vii_article_is_rejected`, `::test_malformed_entries_are_rejected_loudly`, `::test_an_unknown_publisher_or_insecure_url_is_rejected` | Pass |
| Mismatched versions cannot supply exact effects | `::test_exact_effects_require_a_ruleset_they_were_verified_against`, `::test_no_shipped_entry_supplies_a_numeric_effect` | Pass |
| A packaged installation can load the catalog | `uv build --wheel`, installed into a clean venv, `load_catalog()` returned revision `2026-09-08.2` with 5 entries | Pass |
| Unavailable web access does not prevent local advice | `::test_the_packaged_catalog_loads_without_a_network_request` (httpx patched to raise) | Pass |

Suite: `uv run pytest` — 336 passed. `git diff --check` clean.
`uv run python scripts/check_guides.py`: 1 reachable, 4 blocked by Fandom, 0 blocking.

### Remaining limitations

- **No revision permalinks.** `reviewed_url` is null on every entry: Fandom's 403 kept the
  audit from resolving a `oldid` permalink, so entries are current-article links with a
  review date, labelled as such rather than implied to be frozen.
- **`production.ITEM_YIELDS` is still a second table.** A test pins that the overlap with
  the catalog agrees; reconciling them into one is Phase 3 item 5.
- **The catalog covers culture only.** Science, gold, food, production, expansion and the
  tactical families still have no reviewed guide, which is Phase 5 item 5. Until then only
  culture decisions can promise a mechanic-specific reference.
- **`completed_item_facts` is an inference.** A queue changed by hand after production was
  met is indistinguishable from a completion, and nothing before the log started is
  visible. Labelled in the fact's own note.
- **Nothing consumes these contracts yet.** Advisors still emit plain `Insight`s; wiring
  decisions to evidence is Phase 3, and the `/api/briefing` payload does not carry
  evidence or guides until then.

## Phase 3 — State-aware culture recommendations (2026-09-08)

### What changed

- `decisions/context.py` assembles one `DecisionContext` per snapshot: the culture
  comparison, logged queues and observed completions, net gold, happiness, the dated Age,
  human identity, defensive facts, the guide catalog and the player's own reports. It also
  holds the `ContextStore` and its concurrency contract.
- `decisions/candidates.py` builds candidates whose steps come from the catalog. Two rules
  are structural rather than remembered: a named build can never be `READY`, because
  availability, Age applicability and placement legality are all things only the screen
  settles; and a candidate with no reviewed guide gets no steps and therefore is not a
  candidate at all.
- `decisions/culture.py` ranks by stated reasons in a fixed order — a freshly recorded
  attack objective, then the player's stated objective, then established applicability,
  then supported timing and cost evidence — and publishes the reason it chose. There is no
  numeric utility score.
- `production.item_yield` is now the single lookup for what a build item serves, preferring
  the reviewed catalog and falling back to the table renamed
  `UNVERIFIED_ITEM_YIELDS`. `production.mismatch` says when the association it used is only
  a heuristic.
- `GET /api/decisions`, `GET/POST /api/context`, `DELETE /api/context/{id}`, and a
  `decisions` block on `/api/briefing`. Citations are resolved server-side, so an
  unresolvable evidence or guide id fails there rather than rendering as a dead link.

### The worked refinement case

`tests/test_decision_culture.py::test_the_worked_case_chooses_monument_and_shows_what_it_gives_up`
runs the plan's section 6 acceptance case and passes: with both options confirmed
available, both placements confirmed legal, the four previews supplied and the objective
"the next culture increase as soon as possible", the output selects **Monument next in
Test City**, shows that Amphitheater "eventually adds 2 more culture per turn than
Monument, but takes 2 turns longer to start paying anything", and states that the reported
upkeep "would take your net gold from 10 to 8 per turn, all else equal — a scenario
estimate from these figures, not a forecast of your income". Changing the objective to the
largest eventual increase moves the choice to Amphitheater and keeps the delay explicit.
Withdrawing the previews or the availability report removes the named choice and asks only
for what is missing.

### Exit checks and how each was verified

| Exit check | Verified by | Result |
| --- | --- | --- |
| Every section 6 branch | `tests/test_decision_culture.py` — 32 tests, one per branch | Pass |
| The worked refinement case | `::test_the_worked_case_chooses_monument_and_shows_what_it_gives_up`, `::test_changing_the_objective_changes_the_choice_and_explains_the_delay`, `::test_returning_compare_the_options_would_fail_the_case` | Pass |
| Identical state is deterministic | `::test_identical_state_produces_an_identical_decision` | Pass |
| A nearby critical threat changes priority | `::test_an_immediate_attack_objective_defers_culture_without_hiding_it`; and `::test_a_dated_attack_objective_does_not_defer_the_decision` pins that a stale objective does not | Pass |
| A full culture queue avoids duplicate advice | `::test_a_culture_item_already_queued_reports_timing_instead_of_a_duplicate` | Pass |
| Incompatible Age, locked option, missing local capacity or unavailable guide cannot produce an unconditional action | `::test_a_named_build_stays_conditional_even_when_the_player_confirmed_it`, `::test_a_reported_absence_of_options_turns_the_decision_into_a_prerequisite_check`, `::test_local_happiness_room_is_never_inferred_from_the_empire_total`, `::test_a_guide_that_is_not_reviewed_yields_no_steps_and_no_candidate` | Pass |
| A delayed form submitted after a reload is rejected | `::test_a_form_opened_before_a_reload_cannot_attach_to_the_new_session`; `tests/test_api.py::test_a_submission_from_another_session_is_refused_with_a_recoverable_conflict` (HTTP 409 with the current context) | Pass |
| Conflicting same-turn input cannot silently overwrite newer context | `::test_a_stale_submission_is_refused_when_a_dependency_changed` and `::test_a_stale_submission_is_accepted_when_nothing_it_depends_on_moved` | Pass |
| Prose includes a target, a timing and a practical next step | `::test_the_card_names_a_settlement_a_timing_and_a_practical_next_step` | Pass |
| Missing values stay missing rather than zero | `::test_a_missing_metric_is_missing_and_never_zero` | Pass |

Suite: `uv run pytest` — 377 passed. `git diff --check` clean. Manual end-to-end run:
`/api/decisions` returns the resolved brief; a preview submitted against the live session
is accepted and moves the context revision; one carrying an old session is answered 409
with `session_changed`.

Two defects the tests found and fixed, rather than being written around:

1. Player reports were cited as evidence but never entered into the ledger, so every card
   that used one raised on resolution. Reports now become citable facts of their own
   source kind.
2. Confirming an unchanged value moved the context revision, because the stamped
   `base_revision` made an identical submission look new. Comparison is now on what the
   report asserts, so re-opening the panel cannot invalidate commentary for nothing.

### Remaining limitations

- **Nothing renders this yet.** `/api/briefing` carries the decision brief, but `web/app.js`
  still shows the flat insight stream: the brief, the evidence drawer, the how-to and the
  refinement panel are Phase 4. The plan requires Phase 4 to consume this contract, which
  it now can.
- **Culture is the only decision family.** `decisions_for` builds exactly one card. Science,
  gold, food, production, expansion and the tactical families are Phase 5.
- **The context store is in memory.** Reports are lost when the advisor restarts, and are
  discarded on a new epoch by design. Durable storage is Phase 6.
- **Commentary does not yet carry the decision or context revision.** `CommentaryIdentity`
  has the fields and they are still initialised to zero; populating them from the decision
  context is Phase 4 item 2, where the UI needs them to decide whether prose may be shown.
- **`_dependencies` covers the queue, the observed Age and the session.** Those are the
  dependencies that exist today; a preview also depends on placement and on buildings
  present, neither of which any log records, so neither can be watched for change.
- **The Age prerequisite is always UNKNOWN.** `age_prerequisite` returns UNKNOWN
  unconditionally and says why: nothing states the current Age and the catalog establishes
  no Age compatibility. It is a function rather than a constant so Phase 6's explicit
  player setting has somewhere to land.

## Phase 4 — Decision brief and evidence/how-to UI (2026-09-08)

### What changed

- The brief sits above the tabs: status, then the highest-priority decisions, each with
  its next action or inspection. Three grouped decisions by default with a visible
  overflow count, and every distinct critical alert expanded regardless of how many there
  are. Nothing is only in the brief — every original observation stays on its own tab.
- `web/briefing.js` grew the pure rules: `groupDecisions` merges overlapping warnings by
  subject while keeping each one's evidence and severity, `splitBrief` refuses to put a
  critical entry in the overflow, `fingerprint`/`isAcknowledged` make an acknowledgement
  expire when evidence or severity moves, and `commentaryExplains` gates generated prose.
- "Why this? · How to do it" opens inline beside the action, with steps and guide links
  resolved by the server. No URL is produced in the browser or by the model.
- The evidence drawer is a `<dialog>`: facts in words with their value, turn, age, source
  file and limitation; log rows, computed derivations, advisor thresholds, the player's own
  reports and generated interpretation each labelled distinctly; then the ranking reason,
  the unknowns and the source coverage. Internal ids are handles, never the label.
- The culture refinement panel collects the options a settlement offers, the objective, and
  the four preview figures, submits them with the session/epoch/revision they were entered
  against, and reports a conflict rather than guessing.
- "Acknowledge" and "Pin for this session", both recording intent and saying so.
- Keyboard: every control is a real button with a stable `data-focus-key`, focus returns to
  the opener when the drawer closes, and focus survives a repaint. The only live region is
  a dedicated announcer that fires on a new analysis turn, a lost connection or a change in
  critical count — not on the freshness counter, which repaints every five seconds.
- `CommentaryIdentity.decision_revision` is now a fingerprint of the decisions themselves —
  card ids, severities, candidate ids and applicability, evidence — supplied by a
  `Store.identity_provider` hook so `store.py` stays free of the decisions package.
- A Playwright suite in `tests/browser/`, in an opt-in `browser` dependency group and
  excluded from the default run.

### Exit checks and how each was verified

Every row below was run against a real page (`uv run pytest tests/browser`, 17 passed),
except where it says otherwise.

| Exit check | Verified by | Result |
| --- | --- | --- |
| At 1200×842 the top decision and its action/evidence control are visible without scrolling | `test_the_top_decision_and_its_controls_fit_without_scrolling` — measures the bounding box at `scrollY == 0` | Pass: controls end at 639px of 842 |
| At 390-pixel width controls remain usable | `test_controls_stay_usable_and_nothing_scrolls_sideways` — no horizontal overflow, every control inside the viewport | Pass |
| With Ollama unavailable the decision and how-to still work | `test_the_decision_and_its_how_to_work_with_no_local_model` — the fixture server runs with no worker | Pass |
| Every displayed citation opens the correct evidence | `test_every_citation_opens_its_own_observation` — the drawer holds exactly the cited count, each dated and labelled in words | Pass |
| A fourth distinct critical decision renders in the expanded section without an overflow click | `test_five_critical_decisions_all_render_without_an_overflow_click` — a fixture with five real war declarations; scrolling is acceptable, a click is not | Pass |
| Keyboard focus survives refresh and drawer use | `test_keyboard_focus_survives_a_repaint`, `test_closing_the_drawer_returns_focus_to_the_control_that_opened_it`, `test_the_drawer_closes_on_escape_and_still_returns_focus`, `test_every_decision_control_is_reachable_and_operable_by_keyboard` | Pass |
| Changing the preferred action while an old generation finishes must not attach old prose | `tests/test_web_briefing.py::test_generated_prose_may_only_explain_the_decision_context_it_was_written_about` — the decision fingerprint changes, so the prose is refused; also refused on a context, catalog, mode, session or snapshot change | Pass (node) |
| The delayed Oracle-on reply, at the DOM | `test_a_delayed_oracle_on_reply_cannot_repaint_intercepts` holds the response, switches Oracle off, releases it; `test_switching_oracle_off_hides_intercepts_without_waiting_for_the_server` blocks the network entirely | Pass — this closes the Phase 1 limitation |
| No auto-scroll on a turn update | `test_a_repaint_does_not_scroll_the_page` | Pass |
| Announcements limited to meaningful changes | `test_only_meaningful_changes_are_announced` plus the dedicated announcer | Pass |
| Acknowledge and pin record intent, not action | `test_acknowledging_a_decision_removes_it_and_leaves_a_count`, `test_pinning_keeps_an_acknowledged_decision_in_view`; the observation is still on its tab | Pass |
| The refinement panel drives a real change | `test_the_refinement_panel_changes_the_recommendation_and_can_be_cleared` — enters the previews, sees the recommendation become "Build Monument … conditional" with the opportunity cost, checks the figures are cited as "you told us", then clears them | Pass |

Suites: `uv run pytest` — 382 passed; `uv run pytest tests/browser` — 17 passed.
`node --check` on both web modules. `git diff --check` clean. Manually driven in a real
browser: the refinement panel round-trip changes the card from "Inspect Test1's culture
options" to "Build Monument in Test1 CONDITIONAL", and focus returns to the Evidence
button after the drawer closes.

### Remaining limitations

- **Only culture produces a structured card.** Every other family appears as a grouped
  insight entry: its "Why this?" shows the observations and says plainly that no reviewed
  guide covers it yet, and it offers no steps and no evidence drawer. Phase 5 owns this.
- **Acknowledgements and pins live in `localStorage`,** keyed by session, so they are
  per-browser and per-device and vanish with cleared site data. Phase 6 makes them durable.
- **The refinement panel asks about the two culture buildings the catalog covers.** It reads
  that list from the guides the server sent rather than hard-coding it, but a settlement
  offering something else has no field for it — the free-text options box is the only way to
  report that, and it cannot then be previewed.
- **The masthead is tall on a phone.** The brief is below the fold at 390 pixels. The exit
  check is about controls remaining usable, which they are, but the ordering is worse there
  than on a desktop.
- **No visual-regression check.** The two suites cover behaviour and geometry; nothing
  guards against a stylesheet change making the brief unreadable.
- **`test_a_delayed_oracle_on_reply_cannot_repaint_intercepts` patches `window.fetch`.** It
  drives the real app code, but through a seam a player does not have.

## Phase 5 — Frontier exploration and guidance coverage (2026-09-08)

### What changed

- **Frontiers instead of one fitted map.** `tactical.city_clusters` groups known
  city-area tiles by single linkage on hex distance, so an empire on two continents has
  two frontiers rather than one view of the sea between them. Each is labelled by its own
  coordinates — the source is a list of plots the AI targets and says nothing about which
  settlement any plot belongs to, so no settlement name is invented.
- **Every contact is reachable.** The twelve-position cap is gone from both ends: the
  payload carries them all, and `web/tactical.js` provides one view per frontier, a focus
  for distant exposed units of the player's own, and "All contacts". Each view states how
  many recorded positions it leaves out.
- **Stable identities.** `UnitSighting.key` is the AI's own player and unit id, so a
  contact keeps its identity as it moves and selecting a table row selects the same unit
  on the map.
- **Selection through the table.** Two units on one hex share a marker, which can neither
  be clicked apart nor focused, so rows are the selectable control — operable by keyboard,
  synchronised with the marker, with a detail panel giving the observation turn, the
  planned position and the nearest known city tile. Coincident contacts are called out
  explicitly. The table pages and filters; nothing truncates.
- **Marks sized to the span.** `T.frame` derives tile, marker, font and stroke sizes from
  the extent being drawn, clamped at both ends.
- **Decision families.** `decisions/yields.py` is one implementation driven by a `Family`
  descriptor, and `culture.py` is now that family bound into it. Science, gold, production
  and food are promoted alongside culture, each with steps from the publisher's own
  settlement workflow. Same-settlement gaps fold into the worst one.
- **Defence.** `decisions/defense.py` produces an Oracle-only card that leads the brief
  when an objective is freshly recorded and reads as a frontier to re-inspect when it is
  dated. Its steps come from the production workflow for reinforcement and from the
  official naval combat guide for the exposed-unit check.
- **Diplomacy in ordinary language.** `advisors/diplomacy_language.py` reads the log's own
  vocabulary into sentences, and `intel.feed` groups an action's stages into one event —
  split at each recorded ending, so two agreements seventy turns apart stay two events.
  Every event keeps the log's wording in `raw`, carries an `event_type`, and can be
  filtered by player or type.

### Guide research, and what it could not establish

The official 2K game guide has eight gameplay articles and is reachable by our client; the
Fandom wiki answers this client with HTTP 403, so **no new wiki article could be reviewed**
and none was added on trust. Two official articles were read and added:

- **Victories** — the reworked system that replaced Legacy Paths, describing what earns
  military, cultural, economic and science score, and that thresholds are multiples of
  second place. Scoped to the Test of Time update. Its threshold multiples and Innovation
  total are deliberately not recorded: they are version-dependent figures and this catalog
  carries none. This entry is why the output leaderboards are labelled proxies.
- **Naval combat roles and ranges** — scoped to Update 1.3.0, which reintroduced ranged
  naval attacks. It backs the exposed-unit check only, and the candidate says so.

The settlement workflow guide's mechanic keys widened to every yield family plus defence,
because the production menu and placement preview are where *any* build decision is read.

**Expansion is not promoted.** Nothing in the reviewed catalog explains founding a
settlement, so there is no expansion card and no borrowed steps; the economy advisor's
settlement observations stay in the grouped insight stream. That is the plan's own rule
applied rather than worked around, and it is pinned by a test.

### Exit checks and how each was verified

| Exit check | Verified by | Result |
| --- | --- | --- |
| Two distant frontier clusters are individually usable | `tests/browser/test_tactical.py::test_two_distant_frontiers_are_individually_usable` against a fixture with two real city areas; `tests/test_tactical.py::test_distant_city_areas_are_separate_frontiers` | Pass |
| All contacts remain accessible | `::test_every_contact_stays_reachable` (7 of 7 in the browser); `tests/test_web_tactical.py::test_contact_thirteen_is_reachable_by_paging_rather_than_being_dropped`; `tests/test_tactical.py::test_every_contact_is_in_the_snapshot_however_many_there_are` (30 of 30) | Pass |
| Overlapping markers work by keyboard through the table | `::test_overlapping_markers_are_selectable_by_keyboard_through_the_table` — two contacts on 13:12, each selected separately by Enter, marker synchronised | Pass |
| Old goals are dated and expired | `tests/test_decision_families.py::test_a_dated_objective_is_a_frontier_to_re_inspect_not_an_emergency`; the Phase 1 tactical tests still pin the severity split | Pass |
| Missing tactical data cannot produce "safe" | `tests/test_tactical.py::test_missing_tactical_data_cannot_be_read_as_safe`; `test_decision_families.py::test_no_recorded_contact_is_reported_as_a_gap_not_as_quiet` | Pass |
| Each promoted family has practical steps and a reviewed guide | `tests/test_decision_families.py::test_each_promoted_family_gives_practical_steps_and_a_reviewed_guide`, parameterised over all five, asserting the cited guides are reviewed and instructive; `::test_expansion_is_not_promoted_because_nothing_reviewed_explains_it`; `::test_a_family_whose_guides_are_unreviewed_produces_no_card` | Pass |
| Diplomacy keys read as language, grouped, filterable | `tests/test_diplomacy_language.py` (11 tests) and the new `tests/test_intel.py` cases | Pass |

Suites: `uv run pytest` — 427 passed; `uv run pytest tests/browser` — 23 passed.
`node --check` on all three web modules. `git diff --check` clean. Driven manually in a
real browser against a two-frontier fixture: both frontiers, the exposed-unit focus and
All contacts all render; Enter on a shared-tile row selects one contact and highlights its
marker; the real 100-turn session's 900-odd diplomacy rows become 450 readable events with
30 unrecognised, each saying so.

### Remaining limitations

- **The naval guide is the only source for the exposed-unit check.** Nothing official
  describes inspecting a settlement's defences or land unit ranges, so the candidate
  states that its steps describe naval ranges and should be read as a reminder to check
  reach for a land threat. A land-combat article would replace that caveat.
- **No revision permalinks, still.** Fandom's 403 also blocks resolving `oldid`
  permalinks, so every entry remains a current-article link with a review date.
- **Clustering is O(n²) in known tiles.** 61 tiles in the real fixture is nothing, but a
  very large empire late in a game would want a grid index.
- **`_threatened_settlement` gives up with more than one logged settlement.** The AI
  targets plots and no log ties a plot to a settlement, so the card stays about the
  frontier. Matching would need a settlement-position source that does not exist.
- **Contact selection is not persisted across a reload,** by design: the unit ids are the
  AI's own and are not stable across sessions, which is why the epoch changes.
- **The Intel feed is not yet filtered from the UI.** `intel.event_types` and
  `intel.filter_events` exist and are tested, and the payload carries `event_type` and
  `raw`, but the Intel tab still renders the whole feed; wiring the controls is small and
  was left rather than half-done.
- **`also_behind` ratios are shown as percentages** in one line on the card. With five
  yields behind that line is long; if it reads badly in play it should become part of the
  evidence drawer instead.

## Phase 6 — Changes, priorities, and contextual AI (2026-09-08)

### What changed

- **`decisions/changes.py`** keeps a bounded per-sitting history and compares two turns.
  Four refusals are built into it: no history means no trend; a different epoch is not the
  previous turn; a signal whose source coverage moved is `not_comparable` and says which
  source; and `resolved` requires a present observation that the condition lifted, so a
  signal that merely stopped being reported is `no_longer_observed`. Same-turn rebuilds
  replace their entry, and the series keeps observed turn numbers including gaps.
- **`context_store.py`** persists goals, watchlist entries and acknowledgements in one
  versioned JSON file, written through a temporary sibling and renamed so a crash cannot
  truncate it. A damaged file is moved aside and reported. Entries are filed under their
  sitting; another sitting's entries are *offered* with a reason and never applied until
  the player associates them. `--context-file` and `--no-context-file` control where, and
  whether, anything is written.
- **`llm/questions.py`** answers `why`, `inspect`, `what_changes` and `challenge` about one
  decision from that decision's own closed world. Evidence is filtered for the mode before
  the request exists, and the mode plus the snapshot, decision, context and catalog
  revisions are all in the cache key — so a fair answer can never be served from an
  oracle-mode generation, nor one written about a superseded recommendation.
- **Questions run on their own worker pool**, so a question never queues behind a turn's
  commentary, and the deterministic answer is returned immediately in every case.
- **`/api/changes`, `/api/record`, `/api/record/associate`, `/api/question`**, and both
  `changes` and `record` on the briefing. The UI adds a "Since last turn" panel, the
  question and challenge panel, and the association prompt; acknowledgements and pins now
  write to the server's record, with `localStorage` kept only as a fallback for when that
  store cannot be written.
- **`decisions/changes.retrospective`** puts observed changes and acknowledged decisions
  side by side with no arithmetic between them, and says in the payload that nothing there
  shows one caused the other and that no success is being scored.

### Findings from the real local-model run

`gemma4:26b-a4b-it-qat` was asked two questions about a live decision. One returned
malformed JSON and was rejected — the deterministic answer stood and said why, which is
the designed path. The other **passed citation validation while being visibly broken**:
`"...inspect the inspect.LOC_CITY_NAME_TEST1 culture options in Test```json way="`.

That is the plan's warning about citations not being warrants, arriving in practice. Three
structural checks were added — no code fences, a minimum length, and a complete final
sentence — and `MIN_ANSWER`/`FENCES`/`SENTENCE_ENDS` carry a comment saying plainly that
they catch broken output and say nothing about correctness. Re-run with the configured
default `gemma4:31b-it-qat`, all three questions returned coherent answers citing only
supplied ids, with no URL and no fence.

The test suite also surfaced a genuine defect: two `Store` instances created in the same
second produced **identical session ids**, because the disambiguating counter was
per-instance. The session id is what the player's saved acknowledgements are filed under,
so a collision could apply one game's record to another. Session ids now carry a random
suffix, pinned by `tests/test_store.py::test_two_stores_started_in_the_same_second_get_different_sessions`.

### Exit checks and how each was verified

| Exit check | Verified by | Result |
| --- | --- | --- |
| Fair questions never receive Oracle context | `tests/test_api.py::test_a_fair_question_never_receives_intercepted_evidence` — inspects the actual request the worker was handed; `tests/test_questions.py::test_a_fair_request_can_only_hold_what_it_was_handed` and `::test_the_cache_key_separates_fair_from_oracle_and_every_revision` | Pass |
| Missing history does not create a trend | `tests/test_changes.py::test_a_single_observation_is_not_a_trend`, `::test_a_reload_is_not_the_previous_turn`, `::test_a_same_turn_rebuild_replaces_its_entry_rather_than_adding_history`; `tests/test_api.py::test_the_first_turn_reports_no_trend_at_all`, `::test_repeated_reads_of_the_same_turn_do_not_become_history`; `tests/browser/test_questions.py::test_the_first_turn_says_there_is_nothing_to_compare` | Pass |
| Reloads do not import old acknowledgements | `tests/test_context_store.py::test_a_new_sitting_holds_the_old_entries_back_instead_of_applying_them` and the association tests; `tests/test_api.py::test_the_player_record_persists_and_a_new_sitting_holds_it_back` | Pass |
| Unsupported user questions identify missing information | `tests/test_questions.py::test_a_question_with_nothing_to_answer_from_says_what_is_missing`, `::test_an_unsupported_question_is_reported_rather_than_answered` (nothing is asked of the model), `::test_an_empty_challenge_has_nothing_to_weigh` | Pass |
| Fabricated citations, links and actions are rejected | `::test_a_fabricated_citation_is_rejected`, `::test_a_model_written_url_is_rejected`, `::test_visibly_broken_prose_is_rejected_even_when_its_citations_are_valid`, `::test_a_rejected_generation_falls_back_and_says_why` | Pass |
| Slow Ollama never blocks the next decision or the refinement workflow | `::test_a_slow_model_never_delays_the_answer` (the structured answer returns while the model is still inside `generate`), `::test_a_question_does_not_queue_behind_a_turns_commentary` (a question is answered while a commentary generation is blocked) | Pass |
| Source loss is a separate state from resolution | `tests/test_changes.py::test_a_source_that_stopped_being_readable_is_not_an_improvement`, `::test_resolved_requires_a_present_observation_that_the_condition_lifted` | Pass |
| No causation is inferred and no success is scored | `::test_the_retrospective_puts_two_records_side_by_side_and_claims_nothing`, which also pins that the payload has no score field | Pass |
| The store survives a crash and a damaged file | `tests/test_context_store.py::test_the_file_is_written_whole_and_leaves_no_temporary_behind`, `::test_a_damaged_store_is_moved_aside_and_reported_not_dropped`, `::test_a_store_from_a_future_version_is_left_alone`, `::test_a_write_failure_is_reported_and_the_entry_still_applies_for_now` | Pass |

Suites: `uv run pytest` — 486 passed; `uv run pytest tests/browser` — 28 passed.
`node --check` on all three web modules. `git diff --check` clean. One real local-model
smoke test, reported above and separately from the mocked validation. Driven manually in a
real browser: the question panel answers all three questions, a challenge is recorded as
intent, and acknowledging writes to the server record and removes the card.

### Remaining limitations

- **A coherent but off-topic answer still passes.** In the smoke run, `what_changes`
  returned a fluent summary of the decision rather than an answer to the question asked.
  Nothing here can detect that, which is exactly why the prose is labelled interpretation
  and the deterministic answer carries the substance.
- **History is per process.** `context_store` persists the player's own record, but the
  turn-by-turn history does not survive a restart, so "since last turn" is empty after
  one. Persisting it would mean deciding how much to keep and how to migrate it.
- **The retrospective is minimal** — two lists and a caveat. That is deliberate, but it
  means it is not yet useful for reviewing a whole game.
- **Answers are cached in memory only,** so a restart re-asks. Given the cache key
  includes the snapshot revision, most answers would be invalidated by the next turn
  anyway.
- **`ADVISOR_DOMAINS` maps advisors to coverage domains by hand.** A new advisor that
  forgets to register falls back to `("empire",)`, which under-reports comparability
  rather than over-reporting it — the safe direction, but it needs keeping in step.
- **The Intel feed's filter controls are still not wired**, carried over from Phase 5.
- **`/api/question` recomputes the brief on every call.** Fine at this scale, but it means
  a question costs a full decision pass.
