# Reading Civilization VI's live state through the tuner

**Status:** design, awaiting review
**Supersedes nothing.** Extends `2026-09-12-multi-game-advisor-design.md`.

## 1. What this is for

Four Civ VI capabilities are declared unsupported today, and phase 4 ended at a
dead end that no ruleset query could pass: the installed ruleset knows what a
building costs in the abstract, but not what *this* settlement may build or how
long *this* settlement would take. The advisor works around that by asking the
player to read figures off their own screen and type them in.

Civilization VI exposes a debug socket that answers both. This design adds a
second read path beside log tailing, for Civ VI only, and only when the player
has turned the socket on themselves.

Verified against a live match on 2026-09-13, turn 59:

| Question | Answer from the socket |
| --- | --- |
| Amenities in Rome | 3 — one from luxuries, none from civics, two from entertainment |
| Maintenance | 1 total: districts 1, buildings 0, units 0 — against a gold yield of 8 |
| What may Rome build? | Granary, Library, Hanging Gardens — and nothing else |
| How long? | 8, 11 and 23 turns |

The last row is the phase-4 dead end, answered.

## 2. What the spike falsified

Recorded because each cost a real attempt, and because a plan written without
them would repeat the mistake.

| Believed | Actually |
| --- | --- |
| A mod is the way to get richer Civ VI data. | No mod is needed. The base game's own `GameCore_Tuner` Lua state answers everything a mod could, without per-save enablement, patch fragility, or any question about achievements. |
| A mod's `print()` reaches `Lua.log`. | On this macOS build `print()` reaches no file at all — not `Lua.log` (never created), not any other log, not the system log. With the tuner off it is discarded; with it on it goes to the socket. |
| A mod applies to a save you already have. | Only with `<AffectsSavedGames>0</AffectsSavedGames>`. Without it the mod loads, is listed as enabled, and its components are silently never applied. |
| A binding that exists can be called. | `BuildQueue:CanProduce` and `GetTurnsLeft` exist in the GameCore VM and raise `"Not Implemented."` when called. They work only in the `InGame` UI VM. |

## 3. Transport

TCP to `127.0.0.1:4318`, loopback only. The port is open only while the game
runs **and** `[Debug] EnableTuner 1` is set in `AppOptions.txt`.

Framing, verified by implementation:

```
uint32 LE  length of payload including its NUL terminator
int32  LE  tag
bytes      NUL-terminated UTF-8 payload
```

- Tag 4 is handshake. Send `APP:<client name>`, then `LSQ:`. The reply carries
  the application identity and a NUL-separated list of `index`, `name` pairs —
  every Lua state in the running game.
- Tag 3 is a command: `CMD:<state index>:<lua source>`.
- Output returns as tag-4 messages prefixed `O\0<state name>: `. Output longer
  than one packet is split, so every query appends a sentinel and the client
  collects until it sees it.

**State indices are not stable and must never be hardcoded.** In the spike
session `GameCore_Tuner` was 4 and `InGame` was 125, but loaded mods shift the
numbering — a throwaway mod took index 2 and pushed the rest along. The client
resolves a state by name from the `LSQ:` reply on every connection. A hardcoded
index does not fail loudly; it runs the query against a different VM.

## 4. Two VMs, three outcomes

Queries name the VM they need:

- **`GameCore_Tuner`** — the gameplay VM. Treasury and city-growth figures.
- **`InGame`** — the UI VM. The build queue: what a settlement may produce and
  how long each option takes.

A binding has three possible states, and conflating the last two is the defect
this section exists to prevent:

1. **Absent** — the name is `nil`. The game has no such method.
2. **Stubbed** — the name is a function and raises `"Not Implemented."`.
3. **Working** — returns a value.

Stubbed bindings look exactly like working ones until called. `CanProduce` and
`GetTurnsLeft` are both stubbed in `GameCore_Tuner` and working in `InGame`. A
query catalog that recorded only "the method exists" would have shipped a panel
that fails at runtime in every game. Therefore: **the catalog records the VM a
query was verified against, and a `"Not Implemented."` response is treated as
absence of that capability — never as a transient error to retry, and never
blended with a real reading.**

## 5. Components

### `civ_advisor/tuner/protocol.py`
Framing and parsing only. No sockets, no game knowledge. Pure functions over
bytes so the wire format is testable without a game or a server.

### `civ_advisor/tuner/client.py`
Connect, handshake, resolve state names to indices, run a catalog query, collect
to the sentinel, return raw output lines. Every failure mode is a distinct,
named result — port closed, handshake refused, state not present, sentinel never
arrived, Lua raised — because "no amenities data" must never be the message when
the real reason is "you have not enabled the tuner."

The client never accepts Lua from a caller. It accepts a catalog entry's id.

### `civ_advisor/tuner/queries.py`
The catalog: one entry per fact, each carrying its Lua source, the VM it runs
in, the canonical fields it yields, and the date it was verified against a real
game. This is the same allowlist discipline as `READABLE_COLUMNS` in
`ruleset/civ6.py` — the set of things the program may ask is fixed in reviewed
source, not composed at runtime.

**No value that originated with the player is ever interpolated into Lua.** Not
a settlement name, not a goal, not a challenge-box entry. Queries are constants;
their only parameters are integers the program itself derived (a player id, a
city id), passed through a validator that rejects anything that is not an int.

### Wiring
`GameProfile` gains a declaration of which capabilities the tuner can fill,
kept separate from the reader table. A tuner-backed capability is *available*
only when the socket answered this poll. The existing `unsupported` reasons for
`HAPPINESS` and `MAINTENANCE` are replaced by reasons that name the real
condition — the tuner is off — and say the one line to change.

## 6. Provenance

A tuner reading is unlike every other source this program has. A log row is
something the game wrote on its own; a ruleset figure is a fact about the
installed game; a player report is a dated human observation. **A tuner reading
is a value the advisor asked for, at a moment the advisor chose.**

It gets its own evidence source class — `live reading` — carrying the game turn
and the wall-clock instant of the query. It is never folded into `log row`.

Fair or Oracle: **Fair.** Amenities, maintenance and a settlement's build
options are all on the player's own screen. The evidence drawer says the figure
was read live rather than observed in a log, so the distinction stays visible
without being mislabelled as an intercept.

## 7. Honesty when the tuner is off

This is the common case, and it is not an error. The header and any affected
panel say which of the three it is:

- **Not enabled** — `AppOptions.txt` has `EnableTuner 0`. Say so, and quote the
  line to change. Do not imply the game lacks the data.
- **Enabled but not answering** — the game is not running, or is at the menu.
- **Answered, but this figure is not reachable** — the binding is absent or
  stubbed in every VM. This is a permanent property of the game, and reads like
  the existing `unsupported` reasons.

A zero is never shown for an unreachable figure, and no panel silently falls
back to a stale reading from an earlier poll.

## 8. The advisor never enables the tuner

`AppOptions.txt` lives in the game's own directory, and this program is
read-only with respect to both games' directories. The advisor prints the
change and the player makes it. This is not a limitation to route around; it is
the same rule that keeps the program from writing a WAL file beside
`DebugGameplay.sqlite`.

## 9. Security, stated plainly

Port 4318 executes arbitrary Lua inside the running game and has no
authentication. Any local process can connect. Consequences for this design:

- The README says what enabling the tuner exposes, in the section that tells
  the player how to enable it. A player who does not want that trades away the
  tuner-backed panels, which is a legitimate choice the UI must keep usable.
- The advisor connects to loopback only and never listens.
- The query catalog is fixed in reviewed source, and no player-supplied text
  reaches it, so the advisor cannot become the thing that turns someone else's
  input into code in your game.

## 10. Testing

The socket cannot be in the default suite — it needs a running game.

- **Protocol** — pure byte-level tests of framing and parsing, including a
  reply split across packet boundaries and a sentinel arriving mid-packet.
- **Client** — against a fake server replaying frames captured from the real
  game, including the real `LSQ:` reply, so state-name resolution is exercised
  against genuine output with mods shifting the indices.
- **Catalog** — each entry asserts its declared fields against a recorded
  response, and a conformance test fails any entry that declares a capability
  the profile does not, or omits its verified-against date.
- **Absence** — a test per failure mode asserting the *reason* reaches the
  payload, because a blank panel that passes for the wrong reason is the defect
  this project has hit five times.
- **Live** — an opt-in suite, excluded from the default run like `tests/browser`,
  that runs against a real game when one is up.

## 11. Scope

**In:** amenities and their sources; the maintenance breakdown and net gold per
turn; what each settlement may build and each option's completion estimate.

**Out of this cut:** diplomatic state, peace deals, combat odds — none verified
against a live game, so none may be planned yet. Civilization VII — untested;
no claim is made that it has an equivalent socket. Any form of writing to the
game: this path stays read-only, and the tuner's ability to execute commands is
never used.

## 12. Open question for review

The "Refine this recommendation" flow asks the player to type figures the tuner
can now supply. Two readings are defensible: retire the hand-entry path where
the tuner answers, or keep it so the feature still works with the tuner off.
Recommendation: **keep it**, and have the tuner pre-fill it with a live reading
the player can correct — one flow, one evidence trail, and it degrades to
today's behaviour when the socket is closed.
