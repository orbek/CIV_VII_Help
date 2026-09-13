# Real tuner frames, captured 2026-09-13

Raw bytes off the socket of a running Civilization VI, turn 59, two cities
(Rome and Puteoli). Each file is one exchange, framed exactly as the game sent
it: `uint32` LE length including the NUL, `int32` LE tag, NUL-terminated UTF-8.

| File | What it holds | Why it is kept |
| --- | --- | --- |
| `handshake_lsq.bin` | The app identity frame and the full `LSQ:` state list | The only real sample of the state list. **It lists `2 AdvisorProbe` and `111 AdvisorProbeUI` — a throwaway mod that no longer exists.** That is the point: it proves a loaded mod shifts every index after it, so a client must resolve `GameCore_Tuner` and `InGame` by name. |
| `query_maintenance.bin` | Treasury: total 1, buildings 0, districts 1, units 0, gold 152, yield 8 | The maintenance breakdown the Civ VI profile currently declares impossible. |
| `query_amenities.bin` | Rome and Puteoli: amenities, sources, housing, food surplus | Two rows, so parsing is exercised against more than a single city. |
| `query_buildoptions.bin` | What each city may build and its turn cost | The phase-4 dead end. Note Puteoli's costs (60/65/180) dwarf Rome's — real data, not a uniform fixture. |
| `query_not_implemented.bin` | `GetTurnsLeft` in the GameCore VM raising `Not Implemented.` with a Lua traceback | A binding that exists and does not work. Must be read as absence, never as a retryable error. The traceback spans a frame boundary, so it also exercises reassembly. |
| `query_missing_binding.bin` | `type(g.GetAmenitiesNeeded)` -> `nil` | A binding that does not exist at all — the other absence case. |
| `query_buildoptions_ids.bin` | Three settlements with their city ids, and every option's item hash, placement flag and turn cost | Taken on a later day than the others (turn 112, three cities). Kept because it carries both shapes an action needs: an ordinary building that needs no plot, and a wonder that does. It was captured WITHOUT the write spike having run — this query only prints, so no save was risked to take it. |

These are captures, not hand-written. Do not edit them to make a test pass:
if a test disagrees with these bytes, the test is wrong about the protocol.

Re-capturing needs `[Debug] EnableTuner 1` in the game's `AppOptions.txt` and a
running match. The advisor never writes that file; a human sets it.
