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

At the time of trimming (Task 3), none of these five were read by any
reader the Civ VI profile declared — they were trimmed because they were
disproportionately large (each over 100 KB, several hundred KB before
trimming) relative to the files Task 3's readers actually parsed. Every file
a Task 3 reader parses (`DiplomacySummary.csv`, `AI_Tactical.csv`,
`AI_Operation.csv`, `AI_MayhemTracker.csv`, `AI_UnitEfficiency.csv`,
`GameCore.log`) is kept whole, byte-for-byte as captured. (Task 4 later
added a reader for `UnitOperations.log`, which now parses this file in its
trimmed form.)

`AI_Research.csv` and `AI_GovtPolicies.csv` are kept present in the trimmed
form above rather than deleted, because a later phase is expected to want
them. `AI_Military.csv` and `DiplomacyModifiers.csv` are kept present for
the same reason but were NOT trimmed — both were already small (38 KB and
1.7 KB) in the raw capture, so they are untouched at full size.
