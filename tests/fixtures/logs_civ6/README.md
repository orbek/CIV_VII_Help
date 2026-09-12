# Civ VI fixture capture

Captured 2026-09-12 from a real Civ VI game at turn 53, Julius Caesar of
Rome, 6 majors (players 0-5), 9 city-states (6-14), Free Cities at 62,
Barbarians at 63.

Trimmed for repo size, all to the first 400 lines (header plus data rows):
- `AI_Research.csv`
- `AI_GovtPolicies.csv`
- `AI_Diplomacy.csv`
- `AI_Operation_Eval.csv`
- `UnitOperations.log`

None of these five are read by any reader the Civ VI profile declares as of
Task 3 — they were trimmed because they were disproportionately large (each
over 100 KB, several hundred KB before trimming) relative to the files this
task's readers actually parse. Every file a Task 3 reader parses
(`DiplomacySummary.csv`, `AI_Tactical.csv`, `AI_Operation.csv`,
`AI_MayhemTracker.csv`, `AI_UnitEfficiency.csv`, `GameCore.log`) is kept
whole, byte-for-byte as captured.

`AI_Research.csv`, `AI_GovtPolicies.csv`, `AI_Military.csv` and
`DiplomacyModifiers.csv` are kept present (trimmed, not deleted) because a
later phase is expected to want them.
