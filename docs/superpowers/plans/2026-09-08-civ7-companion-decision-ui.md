# Civ VII Companion — Decision UI and Guide-Linked Recommendations

Date: 2026-09-08  
Status: proposed implementation plan; no runtime implementation in this document  
Builds on: current v2 implementation, including the uncommitted commentary/map fixes  
Related decision record: [ADR-001](../../architecture/adr-001-grounded-companion-decisions.md)

## 1. Outcome and scope

The player should be able to answer, within ten seconds of looking at the companion:

1. What deserves attention before I end this turn?
2. What should I do or inspect, in which settlement/frontier, and why now?
3. How do I do that in Civ VII, and where can I read the relevant guide?
4. Which facts support the recommendation, how old are they, and what is unknown?

The first release delivers reliable status, a compact decision brief, actionable guide-linked advice, an evidence drawer, and an explorable tactical view. Subsequent phases add changes over time, player priorities, and contextual conversation. Keep FastAPI, Python advisors, vanilla JavaScript, and SVG. Keep gameplay analysis local; guide links open externally only when clicked. No game-control automation, mod installation, broad web crawl, or UI-framework migration is required.

The added requirement is substantive: appending a wiki link to “improve culture” is insufficient. The recommendation must explain a feasible next inspection/action using the available game context. More specific prescriptions require more specific evidence.

## 2. Findings driving the work

- The turn-99 fixture produces 27 insights, with commentary beginning approximately 4,689 pixels down the page at a 1200 × 842 viewport. The rules and model mostly repeat observations instead of supporting a short decision flow.
- `web/app.js:refresh` independently fetches five endpoints and accepts late responses. Browser reproduction showed an old Oracle-on response restoring intercepted map content after Oracle was turned off.
- `Insight` currently carries one `why` string. It has no structured observation references, prerequisites, steps, guide links, or target settlement identity.
- The map and contact table each cap contacts at twelve. All known city tiles and some distant human units still determine the same bounds. Markers are not selectable or keyboard navigable.
- Tactical city targets and attack goals can outlive recent unit sightings. The dashboard needs observation dates and coverage, not just a completed-turn number.
- LLM validation checks structure/citation identity; it does not prove that generated statements follow from the evidence. Fair mode currently hides all ready commentary because every prompt sees Oracle data.

These are starting conditions, not newly implemented fixes. Preserve the existing working-tree changes while implementing this plan in separately reviewable increments.

## 3. Recommendation contract

Introduce structured decisions assembled from existing ranked insights. Retain the existing `Insight` shape and legacy endpoints during migration; add optional evidence references with defaults, then migrate advisors incrementally.

| Type | Required information |
| --- | --- |
| `SnapshotEnvelope` | Schema version, game identity when known, session/epoch ID, monotonic revision, captured-at time, latest game turn, analysis-through turn, selected evidence mode, source/domain coverage, decision data, commentary status. |
| `EvidenceFact` | Stable ID, source kind (`log`, `player_report`, `derived`), source file and record key where applicable, observed turn, subject ID, value/unit, provenance, freshness, and contributing fact IDs for derivations. |
| `GuideEntry` | Stable ID, canonical URL, reviewed revision/permalink when obtainable, title, publisher, section if verified, mechanic/item keys, independently written concise instructions, reviewed-at date, supported ruleset/version/Age, prerequisites, and review status. Unknown compatibility is explicit. |
| `ActionCandidate` | Action ID, target entity, steps, `why_now`, evidence IDs, guide IDs, prerequisites with `met`/`unmet`/`unknown`, trade-offs, decision-changing unknowns, and applicability (`ready`, `conditional`, `inspect`, `blocked`). |
| `DecisionCard` | Stable decision ID, grouped insight IDs, severity, subject, preferred candidate or inspection, alternatives, evidence mode, observation dates, and an explanation of priority. |
| `PlayerContext` | Explicit player-supplied Age/ruleset, available item choices, preview values, priorities, or acknowledgements; each scoped and dated with an expiry/invalidation policy. |
| `CommentaryIdentity` | Session/epoch, evidence mode, snapshot/decision revision, contributing insight IDs, player-context revision, and knowledge-catalog revision. Attach generated prose only to matching decision context. |

Distinguish three links in the UI: **Evidence** opens observations; **How to do it** opens concise steps and guide links; **Open economy/frontier** navigates within the companion. Do not imply that a button opens or controls an in-game screen.

Every promoted action/inspection must have a reviewed mechanic-specific guide reference or an explicitly labeled broader verified guide explaining the inspection. If a mechanic cannot be sourced, keep the observation visible, state that instructions are unavailable, and do not invent steps. Raw threat counts and AI intent readings cite the game logs; the associated defensive action cites a guide when available. A wiki page never verifies the current save's state.

Provenance propagates through dependencies: a decision, priority change, explanation, or comparison using any Oracle fact is Oracle. Recompute decisions from filtered facts in Fair mode; merely removing the Oracle sentence is insufficient.

## 4. Context available today and the missing-information bridge

| Information | Current support | Required treatment |
| --- | --- | --- |
| Empire yields, settlement counts/cap, military counts | Parsed in `Player_Stats.csv` | Reuse observed values and advisor calculations, with dates. A deficit alone does not establish the best investment. |
| Gold balance/net income and happiness | Parsed, but optional sources can be missing | Never infer affordability from balance alone; consider recurring cost and reserves if known. Global values do not establish a city's local capacity. |
| Current item, city key, progress and estimated completion | Parsed in `CityBuildQueue.csv` | Use for timing and queue trade-offs. Retain city keys if localization is uncertain. One queue row is not a census of all settlements. |
| Leader/civilization identity | Partially resolved from `GameCore.log` | Carry human identity explicitly into decision context; unique recommendations require exact identity and verified mechanic support. |
| Current Age, ruleset, DLC/mod compatibility | No normalized reliable contract yet; Historian events have Age labels | Audit actual sources. Historical Age labels are dated evidence, not proof of current Age after a transition. Unknown means conditional guidance or an optional player setting. |
| Human unlocks, available builds, existing buildings, policies, specialist slots | Not comprehensively represented | Inspect candidate logs before adding parsers. Absence of a record does not mean locked or absent. Offer bounded player confirmation where needed. |
| Tile adjacency, local preview changes, terrain, per-city upkeep | Insufficient for reliable placement optimization | Ask for displayed candidate preview values, or provide an exact inspection workflow. Do not fabricate coordinates or expected gains. |
| Enemy goals and units | Partial, dated Oracle observations, often planned moves | Use as context with coverage and expiry. “No contact recorded” does not mean the frontier is safe. |

The “Refine this recommendation” panel is part of the culture pilot, not deferred behind general chat. Ask only decision-changing questions, for example: “Which culture options are available in this city's build list?” followed by optional displayed completion time, culture change, and maintenance for two candidates. Store these as player reports, permit editing/clearing, and invalidate them after relevant queue/Age/session changes. Manual information must never silently override contradictory fresh log evidence.

Context submissions include session/epoch, target entity, observed turn, and base decision/context revision. Reject stale submissions with a recoverable conflict response, or explicitly revalidate their unchanged dependencies before acceptance. A form opened before a reload must never attach its values to the new session. Accepted input increments the context/briefing revision even if the log files did not change. Invalidation follows relevant dependencies: an unrelated rival event need not discard a city preview, while a relevant queue, placement, Age, or session change does.

## 5. Guide strategy and initial sources

Use the user's chosen [Civilization VII wiki](https://civilization.fandom.com/wiki/Civilization_VII) as the entry point. Recommendation cards deep-link to specific Civ VII articles rather than the homepage or another Civilization title.

Initial discovery inventory, inspected 2026-09-08:

| Source | Planned use | Verification status |
| --- | --- | --- |
| [Culture (Civ7)](https://civilization.fandom.com/wiki/Culture_%28Civ7%29) | Explain the yield and contextual culture decisions. | Article retrieved; the retrieved Sources section is incomplete. Insufficient alone for a complete action catalog. |
| [Monument (Civ7)](https://civilization.fandom.com/wiki/Monument_%28Civ7%29) | A named, conditional culture-building example and prerequisite information. | Article retrieved; numeric effects/unlocks must be checked against the target ruleset before activation. No assertion that the current player has it unlocked. |
| [Amphitheater (Civ7)](https://civilization.fandom.com/wiki/Amphitheater_%28Civ7%29) | An alternative named candidate for the refinement comparison. | Article retrieved; includes historical Age-transition material. Verify applicable rules separately before using any effects or prerequisites. |
| [Specialists (Civ7)](https://civilization.fandom.com/wiki/Specialists_%28Civ7%29) | Explain the specialist option and its local trade-offs. | Article retrieved; different indexed revisions warrant version checking. Do not adopt a universal yield or maintenance formula from this planning read. |
| [Official settlement guide](https://civilization.2k.com/civ-vii/game-guide/gameplay/developing-settlements/) | Cross-check settlement preview instructions and mechanics. | Previously cited by the repository; direct retrieval failed during this planning pass. Reverify before adding new rule-dependent instructions. |

Implementation requirements:

- Ship a small reviewed local JSON catalog under `civ7_advisor/knowledge/`; load it without a network request during play. Start with culture, then cover every recommendation family promoted by the first release.
- Separate link health, editorial review, and installed-ruleset compatibility. A URL returning HTTP 200 is not validation of its claims; a search crawl date is not the game's version.
- Record contradictions between wiki revisions, official rules, and player previews. Prefer evidence matching the installed ruleset; do not silently combine numbers from different versions.
- Keep canonical/current article links separate from reviewed revision permalinks. When a permalink is available, offer the reviewed version alongside the current article. Otherwise label it as a current article with a review date, without implying that its live contents are frozen or verified. The explicit audit reports content changes for review; it never silently replaces the packaged rules.
- Treat unknown-version actions as conditional/inspection candidates. Version-sensitive exact numbers require a compatible reviewed rule or dated player preview.
- Keep summaries short and independently written with attribution. Do not mirror full wiki pages or ingest an entire site. Record attribution/license metadata for any reused material.
- Add an explicit developer-run link/review audit; no background scraping during gameplay. Broken/new/unreviewed pages cannot become executable recommendation rules.
- The LLM selects from supplied guide IDs and action IDs. The server supplies URLs from the catalog; the model cannot invent links or authorize a new mechanic.

## 6. Culture pilot: observable behavior

Use the earlier captured turn-33 example as a regression scenario, not as a claim about the player's current turn: culture 11.0 against a 17.2 rival median; one observed city queue has a Warrior estimated to finish in one turn. Age, building availability, and tile previews remain unknown unless separately supplied.

The initial card should say, in substance:

> **Plan the next culture investment.** Your culture is behind the observed field. The recorded Warrior queue is nearly complete; that makes its next production choice worth reviewing. Check immediate defense needs before changing military production.
>
> **How:** Open that settlement's production choices in-game and inspect the culture options currently available. Compare their displayed culture improvement, completion time, maintenance, and any replacement cost. If a compatible option is unavailable, keep the existing queue and inspect the prerequisite rather than switching to an assumed build.
>
> **Refine:** Supply available options and their previews to compare them for this city. A Monument can be shown as a named candidate only when its Age/ruleset applicability is established; availability remains conditional until confirmed.
>
> **Evidence:** Turn-33 culture comparison and the actual queue observation turn. **Read:** Culture; the selected building's guide; Specialists only if that alternative is relevant.

This is an advisor timing judgment, not proof that finishing the Warrior is globally optimal. An urgent defense signal changes the priority; missing defense coverage must not be treated as peace. The release must support the following branches:

| Scenario | Expected change in the recommendation |
| --- | --- |
| Immediate city attack/defense priority | Keep culture as a deferred watch item; surface defense first. Do not hide a critical alert. |
| Fresh compatible culture item already queued | Show that the gap is being addressed and the queue timing; avoid recommending a duplicate. |
| A city has an idle queue, while another is nearly finished | Direct the inspection to the idle city when coverage identifies it; do not infer other cities' queues. |
| Negative net gold or unknown local costs | Explain the maintenance trade-off; do not present a purchase as affordable or specialists as sustainable. |
| Known incompatible Age/unmet prerequisite | Exclude that named action from ready choices; offer a relevant alternative or prerequisite inspection. |
| Available choices and preview values supplied | Compare those actual choices, show the arithmetic and trade-offs, and recommend conditionally on the stated objective. Do not claim a global optimum. |
| Food/happiness or specialist slot information missing | Show a specific check before any specialist action; empire totals alone cannot validate it. |
| No trustworthy build availability or compatible mechanic | Give the targeted inspection and missing-information panel; never fabricate a build order. |

### Worked refinement acceptance case

Create a synthetic test, explicitly separate from both the player's live save and wiki base numbers. The test establishes Antiquity and a compatible catalog ruleset; a player identifies an idle city as “Test City,” confirms both named choices are available and their selected placement previews are legal, and supplies these hypothetical preview values:

| Candidate | Completion estimate | Added culture per turn | Added gold upkeep per turn | Added local happiness cost per turn |
| --- | --- | --- | --- | --- |
| Monument | 4 turns | 3 | 2 | 2 |
| Amphitheater | 6 turns | 5 | 2 | 2 |

The test also supplies net gold +10/turn, adequate local happiness after either placement, no displacement of an existing building, no recorded urgent defensive constraint with readable defense sources, and the explicit objective “get the next culture increase as soon as possible.” Neither available choice is already queued/built at the selected placement. Inputs are dated to the same decision revision. Do not import these numbers as general rules for either building.

The output must choose **Monument next in Test City**, based on the player's near-term objective and its shorter completion estimate. It must show that Amphitheater provides the larger eventual culture increase but takes two additional turns, and that either reported upkeep would reduce the supplied net gold from +10 to +8, all else equal. That last calculation is a scenario estimate, not a forecast of future empire income.

The how-to must name the city, direct the player to its production choices, select Monument and the previously inspected legal placement, recheck the displayed preview against the supplied values, and confirm in-game if they still match. Link the [Monument guide](https://civilization.fandom.com/wiki/Monument_%28Civ7%29) with the selected action and the [Amphitheater guide](https://civilization.fandom.com/wiki/Amphitheater_%28Civ7%29) with the alternative. The fixture's reviewed instructions must support that navigation; do not invent UI button labels.

Passing requires a selected action, comparison, opportunity cost, practical steps, and item-specific links. Merely returning “compare the options” fails. Changing the objective to the largest eventual culture increase among these otherwise feasible choices must change the recommendation to Amphitheater and explain the delay. Changing availability or invalidating the previews must remove the unconditional choice and request only the missing confirmation.

## 7. Delivery phases

Each phase is a separate reviewable change. Run focused checks while developing and the full suite at release boundaries. Tests must exercise behavior, including failures; source-string assertions alone do not establish UI correctness.

### Phase 1 — Consistent state, coverage, and status

**Files:** `store.py`, `api/app.py`, `api/serialize.py`, `state/build.py`, `advisors/tactical.py`, `llm/worker.py`, `llm/models.py`, `web/app.js`; tests in `test_store.py`, `test_api.py`, `test_tactical.py`, `test_llm.py`, and new browser tests.

1. Publish a coherent immutable snapshot envelope after each rebuild. Add `GET /api/briefing?oracle=...`; derive all its sections from one captured state/insight revision. Existing endpoints remain for compatibility.
2. Add session identity independent of whether archiving is enabled. Detect log resets, seed changes, and backward turns. Treat ambiguous reloads as a new epoch rather than carrying acknowledgements over silently. Seeds alone do not distinguish save branches.
3. Filter Oracle facts and derived decisions on the server before serialization, model prompts, or future persistence. Align legacy state/insight endpoints with the same contract and update tests that currently pin client-only filtering.
4. Reject browser responses from an older request/mode/revision; cancel superseded requests when possible. Hide intercepts immediately on mode change. Preserve selected controls and focus through refresh.
5. Report connected/reconnecting, last successful update, analysis turn, and source coverage. Distinguish empty-but-readable, stale, and unavailable domains. Optional missing files should disable the affected capability without a wall of technical warnings.
6. Give tactical tiles/goals observation turns; define expiry for episodic goals separately from persistent state events such as declared war. Do not carry a historical attack objective as an unqualified immediate threat.
7. Distinguish queued, generating, failed, and ready commentary. Add the commentary identity contract now, initializing decision/context/catalog revisions until the following phases populate them. Audit the coalescing worker: replaced pending jobs must not remain cached as permanently generating; old turns must not overwrite current commentary. Preserve a dated previous result only within the same session and evidence mode.

**Exit checks:** reproduce the delayed Oracle-on response and verify it cannot restore hidden data; pause/fail individual sources and verify honest coverage; interleave rebuilds and requests and verify one revision; reload/save-reset and verify epoch changes; run A→B→C→B pending jobs and verify no permanent spinner.

### Phase 2 — Structured evidence and reviewed guide catalog

**New files:** `decisions/models.py`, `decisions/evidence.py`, `knowledge/catalog.py`, `knowledge/guides.json`, `scripts/check_guides.py`, `tests/test_evidence.py`, `tests/test_guide_catalog.py`. Update advisor modules, serializers, and fixture documentation as needed.

1. Implement the contracts in section 3 with optional/default fields for migration. Use typed source keys into parsed observations; never reconstruct evidence by scraping `why` prose.
2. Attach evidence to the culture comparison, queue, gold, happiness, and defense signals needed by the pilot. Derived comparisons cite all contributing observations and the rule threshold.
3. Review the culture guide entries against the intended ruleset. Confirm article targets and any fragment anchors; annotate unsupported versions and absent instructions.
4. Audit available logs for Age, human identity, unlocks, and local city data. Add a parser only where real sample rows support a useful contract, with a minimal fixture and missing-file behavior. Publish a short capability matrix for fields that remain unknown; an empty file is not a data source.
5. Ensure catalog JSON is included in the installed wheel. Link auditing is an explicit online maintenance command, while unit tests and runtime remain offline.

**Exit checks:** each pilot action resolves its evidence and guide IDs; malformed or non-Civ-VII entries are rejected; mismatched versions cannot supply exact effects; a packaged installation can load the catalog; unavailable web access does not prevent local advice.

### Phase 3 — State-aware culture recommendations

**New files:** `decisions/context.py`, `decisions/candidates.py`, `decisions/culture.py`, `tests/test_decision_culture.py`. Update briefing API and add scoped player-context input/API as required.

1. Assemble decision context from the same snapshot: culture gap, available history, queues, gold/happiness, defense priority, compatible guide entries, identity/Age, and player reports. Preserve dates and unknowns.
2. Generate a small set of reviewed candidates: next build inspection, a compatible named culture build when supported, prerequisite inspection, or a specialist comparison when relevant. Each includes steps, prerequisites, opportunity cost, and direct guide references.
3. Rank by urgent constraints, stated player objective if present, known applicability, and supported timing/cost evidence. Expose the ranking rationale. Do not invent a numeric strategic-utility score.
4. Implement the bounded context panel for missing build choices/previews, including the concurrency contract in section 4. Compute comparisons deterministically; preserve input units and account for costs/benefits explicitly. Missing values remain missing rather than zero. Update commentary's decision/context/catalog identity whenever accepted context changes its recommendation.
5. Reuse validated catalog item semantics in `production.mismatch`; reconcile the existing unverified `ITEM_YIELDS` mapping rather than creating a second contradictory rules table.

**Exit checks:** every branch and the worked refinement case in section 6; identical state is deterministic; a nearby critical threat changes priority; a full culture queue avoids duplicate advice; incompatible Age, locked option, missing local capacity, and unavailable guide cannot produce unconditional actions. A delayed form submitted after reload is rejected; conflicting same-turn inputs cannot silently overwrite newer context. Snapshot prose must include a target/timing and a practical next step, not only the yield deficit.

### Phase 4 — Decision brief and evidence/how-to UI

**Files:** `web/index.html`, `web/style.css`, `web/app.js`; split coherent components into `web/briefing.js` and `web/evidence.js` if useful. Add a small Playwright browser suite and explicit dev-only runner/dependency setup.

1. Put status, highest-priority decisions, and their next inspection first. Default to three grouped decisions plus a visible overflow count; display all distinct critical alerts in a section expanded by default even when more than three exist. Overflow may collapse lower-priority decisions only. Keep every original observation accessible.
2. Group overlapping warnings by subject and decision, preserving distinct evidence and severity. Put “Why this?” and “How to do it” beside the action. Reveal model explanation inline rather than requiring a separate long scroll, but only when its full commentary identity and contributing insight membership match. Legacy or older prose may remain in a separate dated panel within the same mode/session; it cannot explain a changed preferred action as though current.
3. Build the evidence drawer with observation facts, dates, coverage, advisor rule, unknowns, and labeled generated interpretation. Use readable links; do not expose internal IDs as the primary labels.
4. Render compact steps and reviewed guide links; provide the culture refinement panel. External links should preserve the dashboard and expose publisher/version notes when material. No model-generated URLs.
5. Use keyboard-operable controls, focus return on closing the drawer, meaningful map-independent alternatives, responsive stacking, and status announcements limited to meaningful changes. No auto-scroll on turn updates.
6. Add “Acknowledge” and “Pin for this session” controls. These record user intent, not game action execution. Acknowledgements expire/resurface when evidence or severity changes.

**Exit checks:** at 1200 × 842 the top decision and its action/evidence control are visible without scrolling; at 390-pixel width controls remain usable; with Ollama unavailable the decision and how-to still work; every displayed citation opens the correct evidence; a fourth distinct critical decision is rendered in the expanded critical section without an overflow click (scrolling is acceptable); keyboard focus survives refresh and drawer use. Change the preferred action through a player preview while an old generation finishes: old prose must not attach to the new decision.

### Phase 5 — Frontier exploration and guidance coverage

**Files:** `advisors/tactical.py`, `advisors/intel.py`, `decisions/` action adapters, `knowledge/guides.json`, `web/app.js` or new `web/tactical.js`; tactical/decision/browser tests.

1. Add selectable city-area clusters and “All contacts,” pagination/filtering without losing contact thirteen, and synchronized marker/table selection. Use stable player+unit identities within the session.
2. Keep marker and text sizes readable at each zoom. Separate coincident contacts in a selectable list. Do not invent city names or map wrapping where the source cannot establish them.
3. Display observation age, planned position, selected contact details, and off-map counts. Distant exposed own units should have their own selectable focus without shrinking the selected frontier.
4. Add practical, sourced defensive inspection steps to tactical decisions; keep operation odds labeled as AI estimates.
5. Extend reviewed action adapters to science, gold, food, production, expansion, and the remaining promoted recommendation families. Gate every family by the same prerequisites/source rules; do not simply attach a generic homepage link.
6. Translate known diplomacy event keys into ordinary language, retain raw details in evidence, group verified multi-stage events, and filter by player/event type. Unknown events retain cautious readable labels.

**Exit checks:** two distant frontier clusters are individually usable; all contacts remain accessible; overlapping markers work by keyboard through the table; old goals are dated/expired; missing tactical data cannot produce “safe”; each promoted decision family has practical steps and an appropriate reviewed guide reference.

### Phase 6 — Changes, priorities, and contextual AI

**Files:** new `decisions/changes.py`, `context_store.py`; `store.py`, API, LLM prompt/worker/models, and UI modules; history/context/provenance tests.

1. Retain a bounded history of coherent snapshots keyed by session+turn+revision; keep observed turn numbers in time series. Compare like-for-like coverage and rulesets. Same-turn updates should not masquerade as a new turn.
2. Show newly observed/worsening/unchanged/no-longer-observed signals. Reserve “resolved” for positive evidence of resolution; source loss is a separate state.
3. Persist explicit goals, watchlist entries, and acknowledgements in a versioned local store with atomic writes and recoverable errors. In unknown/ambiguous sessions, require explicit association before reusing old plans. Start with a single local JSON store; reconsider storage only when history volume warrants it.
4. Add “Why?”, “What should I inspect?”, and “What would change this call?” tied to the selected decision. Provide separate Fair/Oracle prompt and cache identities. Filter evidence before scheduling inference, and include catalog/decision revision in the cache key.
5. Add a bounded “Challenge my plan” input using the same context and guide IDs. Treat player intent as intent, not an observed completed action. Scope model work to compact relevant facts and reviewed mechanic summaries.
6. Keep claims about numbers, prerequisites, supported actions, and URLs in deterministic structured data. Generated interpretation stays labeled; reject unsupported action/reference IDs and retain the deterministic fallback on failure. Do not label arbitrary model prose verified merely because it includes a citation.
7. Add a short retrospective of observed changes alongside acknowledged plans. Do not infer causation or score strategic success from correlation.

**Exit checks:** Fair questions never receive Oracle context; missing history does not create a trend; reloads do not import old acknowledgements; unsupported user questions identify missing information; fabricated citations/links/actions are rejected; slow Ollama never blocks the next decision or the refinement workflow.

## 8. Dependencies and first release boundary

Implementation order: **Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6**. Phase 2's guide research can proceed independently of Phase 1 coding if parallel work is explicitly chosen. Phase 4 must consume the real culture decision contract rather than a mock card with no actionable backend.

First user-testing checkpoint: phases 1–4, with culture fully usable including its missing-context bridge. First UI release: phases 1–5, with direct guides covering all promoted recommendation families. Phase 6 is the follow-on companion/memory release. General unrestricted chat, exact battle forecasts, automatic in-game actions, and terrain reconstruction remain outside this plan.

## 9. Verification and adversarial release scenarios

- Use the two existing real-session fixtures plus synthetic cases for the culture branches; do not copy the player's entire logs into tests. Cite the turn-33 scenario as a manually reconstructed earlier observation.
- Run focused Python tests for each phase, `node --check` on modified JavaScript modules, and Playwright interactions against a fixture server started with `--no-archive --no-llm`. Mock model states for UI tests.
- At release boundaries run `uv run pytest`, the browser suite, `git diff --check`, packaged-catalog loading, and a manually inspected desktop/narrow-window screen. Online guide checks are separate from deterministic tests.
- Run one real local-model smoke test when Ollama is available, including exact decision/evidence references; report separately from mocked validation. Do not equate well-formed output with strategic correctness.
- Adversarial scenarios: delayed Oracle response; mixed-turn requests; dropped sources; obsolete attack goals; duplicate rival warnings hiding an idle queue; fourth critical alert; contact thirteen; unavailable build; wrong Age; conflicting guide revisions; fabricated model URL; near-complete military queue during an attack; a claimed specialist benefit with missing local upkeep; save reload with stale player reports.
- Ask the player to find a priority, open its evidence, understand the next in-game step, and reach the relevant guide during play. Target ten seconds for the first decision and one interaction to its evidence. Confirm usability by observation rather than treating viewport geometry as proof.

## 10. Completion checklist

Implemented across phases 1-6; each item names where it is verified. Per-phase
verification and remaining limitations are recorded in
[the delivery log](../../architecture/decision-ui-phase-log.md).

- [x] All first-release decisions include a concrete action/inspection, a reason it fits the snapshot, evidence dates, and reviewed guide links. — `tests/test_decision_families.py::test_each_promoted_family_gives_practical_steps_and_a_reviewed_guide` (parameterised over every promoted family), `tests/test_decision_culture.py::test_the_card_names_a_settlement_a_timing_and_a_practical_next_step`, `tests/test_api.py::test_decisions_travel_with_their_evidence_and_guides_resolved`. Expansion is deliberately *not* promoted: nothing reviewed explains it, so it produces no card rather than borrowed steps.
- [x] Culture advice changes appropriately across the section-6 scenarios and can become more specific using actual available choices. — `tests/test_decision_culture.py` (32 tests, one per branch), including the worked refinement case in both objective directions.
- [x] Briefing is useful with Ollama stopped and without a network connection. — `tests/browser/test_brief.py::test_the_decision_and_its_how_to_work_with_no_local_model` runs against a server with no worker; `tests/test_guide_catalog.py::test_the_packaged_catalog_loads_without_a_network_request` patches httpx to raise.
- [x] Facts, advisor judgment, generated interpretation, and player reports are distinguishable. — four `SourceKind`s carried through to the evidence drawer's own labels; `tests/test_evidence.py`, `tests/browser/test_brief.py::test_every_citation_opens_its_own_observation`, and the "you told us" assertion in the refinement browser test.
- [x] Oracle mode and freshness remain correct through delayed responses, missing sources, and reloads. — `tests/browser/test_brief.py::test_a_delayed_oracle_on_reply_cannot_repaint_intercepts`, `tests/test_store.py` coverage and epoch tests, `tests/test_api.py::test_fair_mode_strips_ai_internal_fields_from_the_response_itself`.
- [x] All observations and tactical contacts are accessible; controls and evidence work by keyboard. — `tests/browser/test_tactical.py::test_every_contact_stays_reachable` and `::test_overlapping_markers_are_selectable_by_keyboard_through_the_table`; `tests/browser/test_brief.py::test_every_decision_control_is_reachable_and_operable_by_keyboard` and the focus-return tests.
- [x] Ruleset/guide uncertainty produces conditional or inspection guidance, not invented specifics. — enforced in the types (`ActionCandidate` cannot be `READY` with an unknown prerequisite) and in the catalog loader (no effect without a supported ruleset); `tests/test_decision_culture.py::test_a_named_build_stays_conditional_even_when_the_player_confirmed_it`, `tests/test_guide_catalog.py::test_exact_effects_require_a_ruleset_they_were_verified_against`.
- [x] README explains the new flow, external guide links, source maintenance, optional player context, and later local persistence. — README sections "Before you end this turn", "Since last turn", "Asking about a decision", "Your own notes", "Guides and figures".
- [x] Each completed phase records its verification and remaining limitations; no claims of completion based only on mocks or code inspection. — the delivery log records, per phase, the check that produced each claim, plus manual browser runs and one real local-model smoke test reported separately from the mocked validation.
