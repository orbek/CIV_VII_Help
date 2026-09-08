# Civ VII Advisor v2 grounded-strategy findings

Reviewed 2026-09-07 and completion-audited 2026-09-08 against the current official game guide and all locally archived games.

## Sources

- [Official Victories developer diary](https://civilization.2k.com/civ-vii/game-guide/gameplay/victories/) — current Test of Time victory model.
- [Official Developing Settlements diary](https://civilization.2k.com/civ-vii/game-guide/gameplay/developing-settlements/) — current contextual building, adjacency, maintenance, improvement, and specialist guidance.
- Local log contracts in `tests/fixtures/logs_v2/FACTS.md` — what each numeric field actually records.

## Findings before corrections

| Area | Verdict | Finding and action |
|---|---|---|
| Victory tab and `victory.*` recommendations | **Corrected** | The current official guide says Legacy Paths were dismantled. Military, Cultural, and Economic victories use dedicated point systems; Science uses Innovation and projects. Raw yield/unit totals remain useful strategic-output comparisons but are not victory progress. Rename the surface and all copy; explicitly label every board a proxy. |
| AI `SCIENCE`/`CULTURAL`/`ECONOMIC`/`MILITARY` weights | **Confirmed as log evidence, not mechanics** | The log does show following/stopped state and weight. Keep the Oracle signal, call it an AI strategic focus, and stop calling it commitment to a Legacy Path. `STRATEGY_COMMITTED=75` remains an advisor alert policy. |
| `LEAD_MARGIN=1.25` | **Keep, reframe** | The official victory guide does use changing dominance ratios down to 1.25, but our inputs are raw outputs rather than victory score. Keep 1.25 as a “large output gap” alert only; do not imply it is a victory threshold. |
| Yield-specific building lists and diplomatic actions | **Unknown / too prescriptive** | The current settlement guide says building value depends on base yield, placement, adjacency, specialists, overbuilding, maintenance, civ/leader effects, and plans. Replace fixed build orders with advice to use the detailed in-game preview and compare contextual yield deltas. |
| Settlement slack | **Corrected** | Remove the obsolete claim that every settlement adds Legacy progress. Having cap room is permission, not proof that settling is optimal; require a strong site and acceptable happiness/economic cost in the wording. |
| Over-cap warning | **Partially confirmed by logs** | `settlements_over_cap` is directly recorded, but the exact global happiness penalty was not established by the reviewed current sources. Keep the warning and evidence; remove the universal penalty claim. |
| Negative gold | **Confirmed condition; bounded advice** | The log supports net yield minus maintenance. Keep the warning, but tell the player to inspect the current breakdown rather than promise a specific trade/building fix. |
| Celebration recommendations | **Corrected** | Current rules connect Celebrations to Cultural victory score, while available celebration choices are contextual. Replace the claimed production/culture/gold boost with “review and choose the effect that supports the plan.” |
| Threat, tactical, queue, and Ollama recommendations | **Confirmed/bounded** | These are reactions to quoted log evidence, not claims about hidden combat math. Preserve them. The efficiency table and operation odds already say they are heuristics, not probabilities. |
| All numeric alert thresholds | **Advisor policy, not game rules** | `WAR_INTENT_*`, recency windows, military/yield ratios, queue share, proximity, freshness, and celebration-near are triage settings. No current source can “confirm” them as mechanics. Keep them pending multi-game calibration. |

## Recommendation inventory

This inventory covers every runtime recommendation string. “Log-bounded” means
the action is framed as a response to quoted evidence rather than as a claim
about an undocumented game formula.

| Insight id or family | Verdict | Source and rationale |
|---|---|---|
| `threat.at_war.*` | **Confirmed / log-bounded** | Executed declaration in `AI_DiplomaticActions`; defensive response makes no numeric combat promise. See the local log contract. |
| `threat.war_intent.*` | **Unknown policy / log-bounded** | The AI score is real, but no public mechanic assigns meaning to 50/100. Advice says prepare rather than predicts a declaration. |
| `threat.peace.*` | **Confirmed / log-bounded** | An enacted Peace item is recorded in `DiplomacyDeals.log`; incoming proposals are ignored. Healing/re-garrisoning is strategic judgment. |
| `threat.combat_record.*` and `threat.active_combat.*` | **Confirmed / log-bounded** | Recommendations react to realized `CombatLog` losses and never predict damage. |
| `threat.targeting.*` | **Confirmed / log-bounded** | Coordinates come directly from current `AI_Targets`; the response names that bounding box. |
| `threat.military_ratio.*` and `threat.army_growth.*` | **Unknown policy / log-bounded** | Counts and changes are logged; the ratio/delta trigger and response are advisor triage, not rules. |
| `tactical.enemy_units_near.*` | **Confirmed / log-bounded** | Recent planned tiles come from `AI_Tactical`; distance uses the fixture-verified odd-row offset grid. |
| `tactical.ordered_attack.*` | **Confirmed / log-bounded** | Fires only when an issued order/operation goal overlaps a human-owned city tile. |
| `tactical.matchup` | **Corrected / bounded** | Reports the internal matrix relative to its same-type 100 baseline for every nearby type, labels it a heuristic rather than odds, and adds a caveat when recent realized combat disagrees. |
| `tactical.odds.*` | **Confirmed / bounded** | Quotes `AI_Operation_Eval` as AI confidence context and explicitly says it is not combat probability. |
| `tactical.own_exposed` | **Corrected / log-bounded** | Human type comes from `UnitOperations`, position from the enemy’s current target row, and proximity from rival planned positions. |
| `victory.pursuing.*` | **Corrected** | The [Victories diary](https://civilization.2k.com/civ-vii/game-guide/gameplay/victories/) says Legacy Paths were dismantled. Copy now calls this logged AI strategic focus and directs the player to actual victory score. |
| `victory.you_lead.*`, `victory.leader.*`, `victory.leader_committed.*` | **Corrected** | Raw yields/units are labeled output proxies, never victory progress; current victory systems use dedicated score/Innovation. |
| `economy.behind.science` | **Corrected** | The [settlement diary](https://civilization.2k.com/civ-vii/game-guide/gameplay/developing-settlements/) makes base yields, placement, adjacency, specialists and maintenance contextual; use the detailed preview instead of a fixed build order. |
| `economy.behind.culture` | **Corrected** | Same official contextual-build guidance; includes wonders/overbuilding as comparison factors, not guaranteed prescriptions. |
| `economy.behind.gold` | **Corrected** | Uses the current yield/maintenance breakdown and asks for the best verified net gain instead of promising a named building or route. |
| `economy.behind.production` | **Corrected** | Uses the settlement preview to compare improvements, buildings, adjacency and specialization. |
| `economy.behind.food` | **Corrected** | Uses the official growth before/after preview rather than prescribing fixed terrain/buildings. |
| `economy.settlement_slack` | **Corrected** | Cap room is treated as permission, not proof; obsolete Legacy progress wording was removed. |
| `economy.over_cap` | **Unknown mechanics / bounded** | The over-cap count is logged; because the reviewed source did not establish one universal penalty, the action directs the player to the live happiness breakdown. |
| `economy.negative_gold` | **Confirmed condition / bounded** | Net gold is the logged yield minus maintenance; action asks the player to inspect that breakdown. |
| `economy.celebration` and `economy.rival_celebration.*` | **Corrected / bounded** | Current choices and effects are contextual; copy no longer promises a specific yield boost. |
| `production.own_queue` and `production.mismatch` | **Confirmed / bounded** | Queue and turns-to-complete are logged. Static item categories only fire when every queued item is recognized; otherwise mismatch stays silent. |
| `production.rival_military.*` | **Corrected / bounded** | Rival military queues are a leading signal, not proof of war; copy now requires corroboration from targeting/intent. |

## Threshold inventory

Every numeric trigger is advisor policy. Sources are the code constant, the
fixture contracts, and the archive-wide calibration report—not a claim that
the game itself uses the number.

| Constant | Current value | Verdict / calibration basis |
|---|---:|---|
| `WAR_INTENT_WARN` | 100 | **Unknown policy; keep.** One of one observed current scores crossed it; insufficient sample. |
| `WAR_INTENT_WATCH` | 50 | **Unknown policy; keep.** Lower informational tier; archive report retains raw score distribution. |
| `RECENT_TURNS` | 10 | **Unknown policy; keep.** Shared after-action window. |
| `MILITARY_RATIO_ADVISE` | 1.5 | **Unknown policy; keep.** 1 of 12 archived rival snapshots crossed. |
| `ARMY_GROWTH_TURNS` | 10 | **Unknown policy; keep.** Paired-turn comparison window. |
| `ARMY_GROWTH_DELTA` | 3 | **Unknown policy; keep.** No multi-game outcome basis yet. |
| `NEAR_TILES` | 4 | **Unknown policy; keep.** 1 of 26 current rival positions crossed after corrected odd-r distance. |
| `FRESH_TURNS` | 3 | **Unknown policy; keep.** Bounds stale planned/target positions. |
| `STRATEGY_COMMITTED` | 75 | **Unknown policy; keep/relabel.** A focus threshold, not a game commitment rule. |
| `LEAD_MARGIN` | 1.25 | **Corrected framing; keep.** 4 of 8 output comparisons crossed; it is not the current victory-score threshold. |
| `BEHIND_RATIO` | 0.75 | **Unknown policy; keep.** 1 of 10 archived yield ratios crossed below it. |
| `FAR_BEHIND_RATIO` | 0.5 | **Unknown policy; keep.** Severity tier only. |
| `CELEBRATION_NEAR` | 0.9 | **Unknown policy; keep.** 1 of 14 progress snapshots crossed. |
| `RIVAL_MILITARY_SHARE` | 0.5 | **Unknown policy; keep.** 5 of 12 rival queue snapshots crossed. |
| `QUEUE_STALE_TURNS` | 1 | **Unknown policy; keep.** Freshness rule for dropped/captured cities. |

## Calibration decision

Only two archived games are present, so changing thresholds would overfit. The committed calibration script scans every session, selects the most advanced session once per game, and reports current threshold crossing rates. Run it after more games; change a threshold only with a new dated rationale here.
