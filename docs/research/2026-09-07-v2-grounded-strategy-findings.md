# Civ VII Advisor v2 grounded-strategy findings

Reviewed 2026-09-07 against the current official game guide and all locally archived sessions.

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

## Calibration decision

Only two archived sessions are present, so changing thresholds would overfit. The committed calibration script reports every session and current threshold crossing rates. Run it after more games; change a threshold only with a new dated rationale here.
