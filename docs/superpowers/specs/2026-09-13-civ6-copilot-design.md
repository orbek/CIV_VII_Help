# A grounded copilot: conversation, briefing, and acting under confirmation

**Status:** design, awaiting review
**Supersedes nothing.** Extends `2026-09-13-civ6-tuner-live-state-design.md` and
`2026-09-12-multi-game-advisor-design.md`.

## 1. What this is for

The advisor answers four fixed questions about one decision at a time. The
player asked for something wider: a copilot they can talk to about the turn in
front of them — what the rules say, what the game is doing right now, what to
do next — and, when they choose, one that will do it.

Three decisions were made explicitly before this design was written, and it is
built to honour them rather than to soften them:

| Decision | What was chosen | What this design does with it |
| --- | --- | --- |
| Grounding | *Traceable, or it says it doesn't know.* | Every rules claim resolves against the installed ruleset, the logs or the tuner, and names which. Every number in generated prose must appear in a fact the answer cited, or the prose is rejected and the deterministic answer is shown (§4). |
| Interaction | A conversation box for anything, plus the ranked per-turn briefing. | The briefing is unchanged. The conversation is a second path into the same evidence (§3). |
| Authority | It may act in the game, with the player confirming each action. Chosen against the recommendation, having read the risks. | Acting is designed fully, not half-heartedly: a fixed operation catalog, per-action confirmation, off by default, journaled — and entirely contingent on a spike that has not run yet (§5, §6). |

Two facts frame everything below. The rules the copilot needs are on disk and
authoritative — `DebugGameplay.sqlite` is the game's own compiled ruleset, 429
tables, and `READABLE_COLUMNS` exposes ten of them today; growing that allowlist
deliberately is the grounding work. And writing through the tuner is
**completely unverified**: the socket reads were proven on 2026-09-13; no
command has ever been sent. Whether setting a city's production works, whether
the game validates such a command, and what a rejected one does are unknown.

## 2. What is and is not being claimed

Recorded because each is a claim someone might otherwise assume this design
makes.

| Not claimed | What is true instead |
| --- | --- |
| The copilot understands the rules. | It can look up rows the game's own database states, and quote them with the table, column and row they came from. Conditional effects — the `Modifiers` chain — remain refused, as ADR-002 decided. |
| The model reasons about the game. | The model chooses named questions from a catalog, and writes prose around the facts those questions return. Every arithmetic result it may state is computed deterministically and handed to it as a fact. |
| The copilot can play the game. | If the spike succeeds, it can perform one reviewed operation at a time, each shown to the player and confirmed individually. The first cut has one operation. |
| Acting is safe. | Acting sends Lua into a running game over an unauthenticated socket. This design makes it as safe as it can be made; it does not make it safe. The README says so where it tells the player how to turn it on. |
| Civ VII gets any of the live or acting features. | Civ VII has no tuner socket. Its copilot answers from logs and player reports alone, and every ruleset or live question reports itself unanswerable with that reason. |

## 3. Interaction: the conversation beside the briefing

The briefing stays exactly as it is: ranked decisions, evidence drawer, the
four per-decision questions. The conversation is added beside it, on the
**This turn** tab, as a single box the player can type anything into.

What happens to what they type:

1. The text is trimmed to `ASK_LIMIT` characters and treated as the player's
   words — a question or an intention, never an observation. It reaches exactly
   one place: the prompt that asks the model which catalog questions to
   resolve. It never reaches SQL, never reaches Lua, never becomes a fact.
2. The model returns a list of **named questions** from a fixed catalog (§4.1),
   each with typed parameters. The response grammar restricts the ids to the
   catalog and the parameters to the values valid *this poll* — city names from
   this snapshot, yield names from the fixed list.
3. The advisor resolves each question deterministically against the snapshot,
   the installed ruleset and the frozen tuner reading. Each resolves to facts,
   or to a declared absence naming its real cause.
4. The model is handed the facts and the absences and asked to write an answer,
   citing fact ids from a closed list.
5. The answer is validated (§4.3). If it passes, its prose is shown labelled
   *generated interpretation*. If it fails, the deterministic answer is shown
   instead — the resolved facts in words, each with its source, turn and
   value, and each absence with its reason.

The deterministic answer is always built and always shown first. A slow model
delays nothing; a missing model (`--no-llm`) removes step 2, and the box offers
the catalog's questions as buttons instead, so the conversation degrades to a
menu of grounded lookups rather than disappearing.

**Conversation memory.** Earlier exchanges in the same sitting are offered to
the model as context — the player's words and the advisor's answer text, each
stamped with the game turn it was answered on. They are context only: the
current answer must cite facts resolved *now*, and a number from an earlier
exchange is not an admitted number (§4.3). This is the same rule the evidence
layer already lives by: a figure is never attached to a turn it did not come
from, and an answer about turn 61 may not quietly reuse turn 59's upkeep.

The transcript is in memory, scoped to session and epoch like everything else,
and dropped on reload. The player's notes and acknowledgements are the durable
record; the action journal (§5.6) is durable too. A conversation is not.

## 4. Grounding: the mechanism, made enforceable

Grounding is a property of three closed sets, not of a prompt.

### 4.1 The question catalog

`civ_advisor/copilot/catalog.py` is an allowlist in exactly the sense
`tuner/queries.py` and `ruleset/civ6.py:READABLE_COLUMNS` are: a question that
is not written there cannot be asked. Each entry has an id, a one-line
description the model reads, typed parameters, a resolver over the
`DecisionContext`, and the date it was verified.

The model never writes SQL and never writes Lua. It writes a question id and
parameter values. Every parameter has a type, and the type decides what can
reach the resolver:

| Parameter kind | Validation | Reaches |
| --- | --- | --- |
| `stat` | one of `YIELD_STATS` | a Python attribute lookup |
| `city` | one of the settlement names in *this* snapshot or *this* tuner reading | a dict lookup |
| `type_key` | `^[A-Z][A-Z0-9_]{2,63}$` | a **bound** SQL parameter against an allowlisted table and column — never interpolated |
| `parameter_name` | one of `RULE_PARAMETERS`, a fixed set of `GlobalParameters.Name` values verified against the installed file | a bound SQL parameter |

Nothing typed by the player is a parameter. Player text influences which
questions the model *chooses*; the parameter values are then checked against
sets the program computed itself.

Questions in the first cut, by source:

- **Logs** — `turn.analysis`, `empire.yields`, `empire.comparison(stat)`,
  `empire.net_gold`, `empire.happiness`, `settlements.queues`,
  `settlements.coverage`, `rivals.yields`, `defense.objectives` (Oracle),
  `decisions.brief`, `player.reports`.
- **Installed ruleset** — `ruleset.building(type_key)`,
  `ruleset.district(type_key)`, `ruleset.unit(type_key)`,
  `ruleset.technology(type_key)`, `ruleset.civic(type_key)`,
  `ruleset.improvement(type_key)`, `ruleset.policy(type_key)`,
  `ruleset.government(type_key)`, `ruleset.resource(type_key)`,
  `ruleset.parameter(parameter_name)`.
- **Tuner** — `settlement.amenities(city)`, `settlement.build_options(city)`,
  `empire.upkeep`.

### 4.2 Growing the ruleset allowlist, table by table

The copilot's rules questions are only as good as `READABLE_COLUMNS`. Ten
tables are exposed today. This design adds, each verified read-only against
the installed `DebugGameplay.sqlite` on 2026-09-13 (18,051,072 bytes, written
12:55 that day):

| Table | Columns added | Sample row, read that day |
| --- | --- | --- |
| `GlobalParameters` | `Name`, `Value` | `CITY_AMENITIES_FOR_FREE` = 0; `CITY_GROWTH_THRESHOLD` = 15; `CITY_MIN_RANGE` = 3; `TRADE_ROUTE_BASE_RANGE` = 15; 476 rows |
| `Improvements` | `ImprovementType`, `PrereqTech`, `PrereqCivic`, `Housing` | `IMPROVEMENT_FARM`: Housing 1 |
| `Improvement_YieldChanges` | `ImprovementType`, `YieldType`, `YieldChange` | Farm: food 1, production 0 |
| `Policies` | `PolicyType`, `GovernmentSlotType`, `PrereqCivic` | `POLICY_URBAN_PLANNING`: `SLOT_ECONOMIC`, `CIVIC_CODE_OF_LAWS` |
| `Governments` | `GovernmentType`, `PrereqCivic`, `Tier` | — |
| `Government_SlotCounts` | `GovernmentType`, `GovernmentSlotType`, `NumSlots` | Classical Republic: diplomatic 1, economic 2, wildcard 1 |
| `Resources` | `ResourceType`, `ResourceClassType`, `Happiness`, `PrereqTech`, `PrereqCivic` | `RESOURCE_SILK`: luxury, Happiness 4; `RESOURCE_IRON`: strategic, 0 |
| `Resource_YieldChanges`, `Terrain_YieldChanges`, `Feature_YieldChanges` | the type key, `YieldType`, `YieldChange` | — |
| `Buildings` (existing) | + `Housing`, `Entertainment`, `CitizenSlots`, `IsWonder`, `RequiresPlacement` | Granary: Housing 2; Arena: Entertainment 2 |
| `Districts` (existing) | + `Housing`, `Entertainment`, `CitizenSlots`, `Maintenance` | Entertainment Complex: Entertainment 1 |
| `Units` (existing) | + `BaseMoves`, `Range`, `Domain`, `PromotionClass` | Archer: moves 2, range 2, land, ranged |

Two things stay refused, unchanged from ADR-002. The `Modifiers` chain: a
policy's row says which slot it fills and what unlocks it, and nothing about
what it does — `ruleset.policy` therefore returns those two figures and a
`RulesetMention` that the policy's effect is defined by a modifier the file
does not quantify. And `Government_SlotCounts` gives the slot count of a
government; it does not say which policies the player has slotted, which no
log records either.

`GlobalParameters` is read through a fixed allowlist of names,
`RULE_PARAMETERS`, not by any name the model produces. A parameter the model
asks for outside that set is `Absence(NOT_IN_CATALOG)`, and adding a name means
reading its row and writing it into the set — deliberate growth, one line at a
time. The phase-4 finding that "the correct join for government slots was not
found" is answered: `Government_SlotCounts(GovernmentType, GovernmentSlotType,
NumSlots)` is the table, and it is now in the allowlist.

### 4.3 The number rule

Today's validation rejects generated prose that cites an id the decision did
not supply, contains a URL, is fenced, or is truncated. Those catch broken
output. The player's grounding decision needs a check on *content*, and this is
it, stated so it can be implemented and tested rather than aspired to:

**Every number in the generated text must be a number that appears in a fact
the answer cited. Otherwise the answer is rejected and the deterministic
answer is shown, with the rejection reason naming the ungrounded number.**

Precisely:

1. **What counts as a number.** Every maximal match of
   `-?\d+(?:,\d{3})*(?:\.\d+)?%?` in the text, after every bracketed citation the
   answer is allowed to make (`[comparison.culture.81]`) has been removed, and
   every number word from two to twenty, the tens to ninety, *hundred* and
   *thousand*. The word *one* is not a number: it is a pronoun in most English
   sentences ("one settlement", "one of"), and treating it as a numeral would
   reject prose for grammar. The prompt instructs the model to write quantities
   as digits; the word list catches it not doing so.
2. **Where an admitted number may come from.** Only the facts whose ids the
   answer cited. From each such fact: its `value` if numeric; its
   `observed_turn`; and every numeral in its `note`, because notes are written
   by the deterministic layer from the data ("Threshold 12", "luxuries 3").
   Nothing else — not the text of the player's message as typed (rule 7 says
   what may be done with those), not the previous exchange, not the analysis
   turn unless a cited fact carries it (`turn.analysis` exists so the model
   can cite it). A **player report** is a
   cited fact like any other: it is a first-class `SourceKind`, dated to the
   turn it was read and stamped with when it was entered, so a figure the
   player recorded through Refine is traceable and may be quoted — under rule
   6.
3. **How a written number matches.** A numeral `N` written with `d` decimal
   places matches an admitted value `V` when `N == round(V, d)`. A numeral
   ending in `%` also matches `V` when `N == round(100 · V, d)` and the fact's
   unit is `ratio`. Thousands separators are stripped before comparison. A
   negative numeral matches only a negative value.
4. **Arithmetic is never the model's.** "Your net gold is 7" passes only
   because a cited `gold.net.59` fact has value 7 — the deterministic layer
   computed it. The model may not subtract 1 from 8 in prose; if it does and
   no fact says 7, the answer is rejected. Any figure a player might want
   derived is therefore a resolver's job, and adding one means adding a
   `DERIVED` fact that cites its inputs.
5. **An answer with no citations may contain no numbers.** "That is not
   something the advisor can see" is a grounded answer. "It is usually about
   10 turns" is not, and is rejected.
6. **A player's figure is attributed, or the answer is rejected.** When a
   number in the prose is grounded *only* by a cited `player_report` fact, the
   prose must attribute it — one of a fixed set of phrases: *you reported*,
   *your report*, *you told the advisor*, *you entered*, *you recorded* — so
   "the 8 turns you reported on turn 59" passes and "the Granary takes 8
   turns" does not. The game did not say 8; the player did, and the sentence
   must say so. This is the provenance rule applied to prose: the drawer
   already badges the fact *your report*; the words may not un-badge it.
7. **A number the player just typed is their claim, not a fact — and a
   grounded figure that disagrees with it is stated, never reconciled away.**
   Ruled in review: a number typed into the box is neither dated nor stored,
   and admitting it as citable would launder the player's own guess into an
   apparent fact reflected back at them as established. So it is not a
   citation. The prose *may* repeat it, attributed as a claim made a moment
   ago — a second fixed set of phrases, kept apart from rule 6's because the
   two are different in kind: *you mention*, *you mentioned*, *you say*, *you
   wrote*, *your message*. "You mention 8 turns" passes; "the Granary takes 8
   turns" does not, and neither does "the 8 turns you reported" when nothing
   was reported. And when the answer cites a grounded figure for the same
   thing, the prose must carry that figure too, beside the claim: "you mention
   8 turns; the tuner read 4 for the Granary in Rome on turn 49" — both
   numbers, the disagreement named, neither preferred. This is the rule the
   tuner work already settled for a reading's turn against the logs' turn,
   applied to a player's figure against the advisor's: two sources that
   disagree are both reported as read. A player misremembering a figure and
   the advisor quietly adopting it is exactly how a grounded system starts
   giving ungrounded advice.

   Corrected after implementation: the first draft wrote `[\d,]*`, which swallows a
   trailing separator — "First 9, then 11." yielded `9,` and failed to match the
   fact holding 9. The form above still admits a thousands separator (`1,250`)
   without absorbing the comma that ends a clause.


   What the check enforces, stated so nobody relies on more: a repeated typed
   numeral must be accompanied by a claim phrase, and — when the answer cites
   any fact with a numeric value — the prose must also state at least one of
   the cited values. That is a mechanical proxy for "the disagreement is
   named"; whether the two numbers are about the *same thing* is judged by the
   player from the evidence drawer, as in §4.3's closing paragraph. The
   deterministic answer always lists the player's typed numbers as *your
   statement, not a figure the advisor holds* beside every grounded figure it
   resolved, so the comparison is on screen whether or not the model writes
   it.

The same check is applied to the four existing per-decision questions. The
rule is one function, `copilot/grounding.py:check`, and both `questions.py` and
the conversation call it.

What this check does not do, stated so nobody relies on it: it does not verify
that a number is attached to the *right* noun. "Rome has 3 amenities" passes if
a cited fact has value 3, even if that fact is Puteoli's. The evidence drawer
under the answer shows every cited fact with its subject, which is how a player
catches that — and why generated prose stays labelled *interpretation* while
the drawer stays labelled *evidence*.

### 4.4 Sources stay distinct

A tuner reading, a ruleset figure, a log row, a player report and an advisor
rule are five `SourceKind`s today, and the copilot adds none and blends none.
Every fact a catalog question returns carries the kind it was built with, and
the deterministic answer says it in words: *read live on turn 60*, *from your
installed ruleset*, *from Player_Stats.csv, turn 59*, *your report, turn 58*.
A question that would need two kinds — "can Rome afford a Library?" — resolves
to two facts (the ruleset's maintenance figure and the live net gold) and, if
a `DERIVED` comparison is wanted, a third fact citing both. The model may cite
all three; the drawer shows each with its own badge.

### 4.5 Absence is declared, with its real cause

Each unanswerable question resolves to an `Absence` carrying a kind the page
branches on, not prose alone:

| Kind | Meaning | Detail carries |
| --- | --- | --- |
| `not_logged` | this game writes no log that could answer it | the profile's own `unsupported` reason |
| `tuner_absent` | a live reading was needed and there is none | the `TunerUnavailable` cause — one of the six, after §4.6 — and the tuner's own reason text |
| `ruleset_unavailable` | this game ships no ruleset, or the file could not be opened | `RulesetProvider.reason` |
| `no_such_row` | the ruleset has no row for that key | the key and the table |
| `oracle_hidden` | the answer exists and Oracle is off | which capability |
| `bad_parameter` | the model named a city or key outside the valid set | what was named |
| `not_in_catalog` | the model asked for something no question covers | — |
| `answered_empty` | the source was read, answered, and holds nothing for this subject | which source answered, what it holds nothing of, and the turn it answered at |
| `ruleset_schema` | a ruleset query failed at the database because a table is not the shape this advisor expects | which table and column, and that a mod or patch may have reshaped it |

The last two exist because each was once said as something else, and both are the
§4.6 rule applied again. An EMPTY RESULT is an answer -- "you have reported nothing
this sitting", "the tuner says this settlement can build nothing", "the reply names no
settlement called X" -- and was being rendered as `CANNOT`: an inability to see, about
sources that had just been read. A RESHAPED TABLE is not a missing row: the query never
ran, so `no_such_row` would assert a fact about the player's file that nothing read.
Each is established by consulting the source -- the reply's own rows, the reading's own
turn, the database's own `table_info` -- never inferred from the shape of a failure.

The deterministic answer lists every absence with its detail. The model is
given the same list and instructed to say what it could not find rather than
fill it. Both are then held to §4.3: an absence contains no numbers, so an
answer that explains an absence and invents a figure to compensate is
rejected.

### 4.6 Absence must be established too: the `EnableTuner` defect

"It says it doesn't know" is itself a claim, and it is held to the same rule as
every other: established from a source, never inferred from one observation
when an authoritative source is at hand and unread. The tuner package has a
defect of exactly this shape today, confirmed against the live game on
2026-09-13, and it is fixed as part of this design because it is the copilot's
subject.

**The defect.** `open_tuner` returns `TUNER_OFF` — *"its tuner socket, which is
off. Set `EnableTuner 1` under `[Debug]` in the game's `AppOptions.txt` and
restart the game"* — whenever `socket.create_connection` is refused. But
refused does not mean off. With `EnableTuner 1` set on this machine, refused
connections still occur, and the advisor would tell the player to change a
setting they have already changed: a false reason for absence, inferred from
one observation.

**What was established by running it:**

| Observation | Consequence |
| --- | --- |
| A second connection opened while the first is held succeeds. | The socket is multi-client. No design may assume one client at a time, and holding a connection is never the cause of another's refusal. |
| A reconnect 0.2 s after closing succeeds; one 3 s later was refused. | Refusals are not a rate limit. |
| Refusals cycle while the game sits at the **main menu**. In a loaded match, during the read spike, the listener was stable across many connections and queries. | A refused connection has at least three causes: the flag is 0; the flag is 1 but the game is at the menu, between screens, or not running; or the file cannot be read to say which. |

**The fix.** Establish the flag by reading `AppOptions.txt` — on this install
`~/Library/Application Support/Sid Meier's Civilization VI/Firaxis Games/Sid
Meier's Civilization VI/AppOptions.txt`, the parent of the game's `Logs/`
directory, where line 75 reads `EnableTuner 1` under `[Debug]` (line 73),
preceded by the comment `;Enable FireTuner.`. Reading it is permitted, and the
distinction must be stated plainly because it is easy to misread: **the
read-only rule forbids writing under either game's directories. It has never
forbidden reading there** — the program already reads the logs and
`DebugGameplay.sqlite` from inside those directories. The advisor opens
`AppOptions.txt` read-only, parses the `[Debug]` section only, and never writes
it.

Then, on a refused connection:

| The file says | Cause | Reason shown |
| --- | --- | --- |
| `EnableTuner 0`, or no such line | `not_enabled` — now **true** | the existing sentence: set `EnableTuner 1` and restart the game |
| `EnableTuner 1` | `not_answering` | *the tuner is enabled but the game is not answering; it may be at the main menu, between screens, or not running.* The player is not told to change a setting that is already correct. |
| the file is absent or unreadable | `unestablished` — new | *the tuner socket refused the connection and `AppOptions.txt` could not be read to say whether the tuner is enabled* — naming the path tried. The two possibilities are stated; neither is asserted. |

`NOT_ENABLED` and `NOT_ANSWERING` keep their names and now carry their true
meanings: the first is asserted only when the file was read and says so; the
second covers both "connected but no reply" (as today) and "flag on, connection
refused", with the detail sentence saying which. One new member,
`UNESTABLISHED`, is needed for the case where the advisor genuinely cannot tell,
because collapsing it into either of the others would repeat the defect. The
five ways a tuner figure can be absent become six, and the README's list is
updated to say so.

**A single refusal is not evidence of anything.** Measured on 2026-09-13:
against a stable loaded match, 8 of 8 connections succeeded; during menu and
load transitions the listener cycles and a connection is refused. So
`open_tuner` retries a refused connection a bounded number of times —
`CONNECT_ATTEMPTS = 3`, `CONNECT_RETRY_SECONDS = 0.25` apart, under a second
in total — before it consults the file at all. Two refusals in a row are still
not a fact about the flag; they are what sends the advisor to read the file
that is. The retry is bounded because a poll runs every second and must not
stall behind a game that is genuinely closed.

The file is consulted only when a connection is refused, and only for the game
whose default directory it lives in — a `--logs-dir` override points at logs,
not at the game, and says nothing about where `AppOptions.txt` is.

**The general rule this adds to §4.** An `Absence` is a claim about a source.
Its `kind` and `detail` must come from having consulted that source — the
profile's declaration, the tuner's own reply or the file that configures it,
the ruleset's own rows — and never from the shape of a failure alone. Where the
advisor cannot consult the source, the absence says that, as `unestablished`
does, rather than choosing the likeliest story.

## 5. Acting: the design, contingent on the spike

### 5.1 Two rules that do not move

**Read-only with respect to both games' directories stays absolute.** Acting
through the socket is a different thing from writing the player's files, and
this design says so plainly: the advisor still never writes `AppOptions.txt`,
never leaves a file under a game folder, never touches a save. What acting
writes is a **command into a running game's memory**, over a socket the player
opened, into a match the player is playing. The journal that records it lives
under `~/.civ-advisor/<game>/`, beside the player's notes, never beside the
game's own files.

**No player-supplied text ever reaches the socket.** This was true of reads and
is true of writes. An operation's parameters are integers the program read
from the game itself this poll — a city id and an item hash from the tuner's
own reply — and the model addresses them by name; the server maps the name to
the id. A name that does not appear in this poll's reading is refused before
anything is rendered.

### 5.2 The operation catalog

`civ_advisor/tuner/commands.py` is the write-side allowlist, the mirror of
`queries.py`. The model never composes Lua. It selects an operation id from a
catalog whose Lua is a module constant, and supplies parameter values that are
validated types — `int`, never `bool`, never `str`. Rendering an operation
emits a prefix of Lua integer literals (`local cityId=3 local itemHash=...`)
from those validated ints, followed by the constant body. A body contains no
placeholder; a test asserts it.

The first cut has one operation: **`set_production(city, item)`** — set a
city's current production to a building the game offered that settlement this
turn. It exists because it is the one operation a spike can prove reversible:
set it, read it back, set it back. Anything requiring a plot — a district, a
wonder with `RequiresPlacement` — is excluded, and the game's own reply tells
the catalog which items those are.

Where the Lua comes from, and what is known about it. The game's own
production UI, `Civ6.app/Contents/Assets/Base/Assets/UI/Panels/ProductionPanel.lua`
(read from the installed game on 2026-09-13; nothing was written there), sets
production at lines 334–370:

```lua
local tParameters = {};
tParameters[CityOperationTypes.PARAM_BUILDING_TYPE] = buildingEntry.Hash;
GetBuildInsertMode(tParameters);
CityManager.RequestOperation(city, CityOperationTypes.BUILD, tParameters);
```

and reads the queue back at line 1894 with
`buildQueue:GetCurrentProductionTypeHash()`. That establishes the bindings the
UI uses in the `InGame` VM. One thing about that VM *is* settled: reading the
game's turn there, which the tuner spec left unverified, was confirmed against
a loaded match on 2026-09-13 — `Game.GetCurrentGameTurn()` answered 49 in
`InGame`, with build options returned for two cities — so build options are
dated by the game's own turn and will not go dark. The README's paragraph
saying otherwise is retired. It establishes **nothing** about whether a chunk
sent through the tuner socket may call them, whether `CityManager` validates
the request, or what a refused request does. `GetCurrentProductionTypeHash`
was found *absent* in `GameCore_Tuner` during the read spike; whether it is
present in `InGame` is unverified. These are the questions §6 exists to
answer.

### 5.3 Proposals, and confirming one

An action begins as a **proposal**. The model may include one in a composed
answer only when acting is enabled for this run *and* this poll's tuner
reading includes the city ids and item hashes the operation needs; otherwise
the response grammar has no `proposal` field at all. That reading —
`build_option_ids`, the walk that carries each city's id and each item's hash —
is taken only on a run started with `--allow-actions`. A normal advisory run
never asks for it: the read surface stays proportional to what the run can do,
and a poll costs one query fewer. A proposal names the
operation, the city and the item — by name, from enums built from this poll's
reading — and the evidence ids that motivated it.

The server turns that into a `Proposal` the player sees whole:

- the operation in words ("Set Rome's production to Granary");
- the **exact rendered Lua** that would be sent;
- the evidence behind it, resolved — the same facts the answer cited;
- what the city is building now, from this poll's reading, and the reversing
  operation ("set it back to Monument") where one exists;
- the game turn the reading came from and the instant it was read;
- a plain sentence: *the advisor cannot undo this; it can only propose the
  reverse.*

The player confirms **each proposal individually**, by a button that sends the
proposal id, the snapshot revision and the reading turn back. There is no
"confirm all" and no "always allow". A proposal can be confirmed once, expires
when the game turn advances or after `PROPOSAL_TTL` seconds, whichever comes
first, and is refused if the snapshot revision it was built on has been
superseded.

On confirmation the server opens a fresh tuner connection with writes enabled,
asks the game its turn, and refuses if it differs from the proposal's — a
proposal written about turn 59 is not sent into turn 60. Only then is the
operation rendered and sent.

### 5.4 Off by default, per run, loopback only

`--allow-actions` enables acting for one run. Without it:

- `POST /api/copilot/act` answers 403 with a reason that names the flag;
- the compose grammar has no `proposal` field, so the model cannot propose;
- no `ActingTuner` is ever constructed. The read-side `Civ6Tuner` has no
  `perform` method — not a disabled one, no method — so a normal run cannot
  write to the game by any path.

`--allow-actions` refuses to start with a non-loopback `--host`. The advisor's
own HTTP port is the only route to the act endpoint, and it stays on
`127.0.0.1`. Any local process that can reach that port could already reach
the tuner's port directly, so acting through the advisor gives a local
attacker no capability the open tuner had not already given them — which is
a statement about the tuner's threat model, not a reassurance, and the README
says both halves.

### 5.5 Outcomes, rejection, and partial application

One proposal is one operation is one Lua chunk with one `RequestOperation`.
There is no batch, so nothing can be half-applied within a proposal. A plan of
several steps is several proposals, each confirmed on its own; if the third is
refused, the journal shows two applied and one refused, and the page shows
the same.

Every confirmed proposal ends in exactly one of four outcomes, decided by
reading the game back, never assumed from the absence of an error:

| Outcome | How it is decided | What the player sees |
| --- | --- | --- |
| `not_sent` | the turn had moved, the tuner was gone, the journal could not be written, or a parameter failed validation | the reason; nothing reached the game |
| `rejected` | the chunk's guard said the game refuses the operation, or Lua raised | the game's own reply text, verbatim, labelled as the game's |
| `requested_unconfirmed` | the request was sent without error, but the read-back does not show the new item | both hashes, and that the advisor does not know whether it took |
| `applied` | the read-back names the requested item | the before and after items, and the reversing proposal |

`requested_unconfirmed` is a real outcome, not an error to retry: the read
spike showed the game can accept a call and do nothing visible. The next
poll's log row is the second witness, and the *Since last turn* panel will
report the city's queue moving or not moving as it does any other change.

### 5.6 The journal

Every proposal that reaches `POST /api/copilot/act` is journaled — confirmed
or refused, applied or not — in `~/.civ-advisor/<game>/actions.jsonl`, one
JSON object per line, appended and fsynced before the operation is sent. If
the journal cannot be written, the operation is `not_sent`: the advisor will
not act where it cannot record having acted.

A journal entry carries: its id; the wall-clock time; session and epoch; the
game turn as read immediately before sending and the snapshot revision the
proposal was built on; the operation id, the names the model used and the
integers they resolved to; the rendered Lua; the evidence ids and their values
at the time; the player's confirmation instant and the save acknowledgement
(§5.7); the outcome and the game's reply lines; the before and after read-back.

`GET /api/copilot/journal` returns it, newest first, and the page shows it
under the conversation as *What the advisor did, and why*. It is the player's
record of every command sent into their game, and it is never trimmed by the
program.

### 5.7 Saving first

The advisor cannot verify that the player has a save they would return to. It
could `stat()` the Saves folder, read-only, but a file's presence proves
nothing about which save it is or whether they would want it, and the game
autosaves anyway. So the design does not gate on a file. It gates on the
player: the **first** confirmation of each sitting requires ticking *I have a
save I would go back to*, that acknowledgement is journaled with its instant,
and every proposal card repeats that the advisor cannot undo. A player who
would rather not tick it does not act.

### 5.8 Where acting reaches the evidence layer

An action the advisor took is not an observation. The journal is the record;
the log row that appears next poll is the evidence. Nothing in `decisions/`
reads the journal, and no fact is built from a command having been sent. If a
player asks "did that work?", `settlements.queues` resolves from the log, the
answer cites it, and the journal entry sits beside it labelled as what it is.

## 6. The spike, and what each outcome means

Everything in §5 is contingent on one experiment that Task 1 of the plan
performs first: on a **throwaway save**, with the tuner on, attempt one
reversible operation — set a city's production to another building the game
offers it, read the queue back, set it back, read it back — and record every
frame the game sent.

The spike also reads, before trying anything, `ProductionPanel.lua` lines
2880–2900 (`GetBuildInsertMode`) to record which insert-mode values this
version of the game uses, and probes which of `CityManager.CanStartOperation`,
`CityOperationTypes.VALUE_EXCLUSIVE`, `Cities():FindID` and
`GetCurrentProductionTypeHash` are present in `InGame` — each of the three
states the read spike taught: absent, stubbed, working.

| Outcome | What was observed | What it means for this design |
| --- | --- | --- |
| **A. Applied and reversible** | the request changed the queue, the read-back showed it, the reverse restored it, the game's UI agreed | §5 proceeds as written. Progress on the displaced item is checked and recorded: if switching loses progress, the proposal card must say so, and "reversible" is qualified. |
| **B. Accepted, no effect** | no Lua error, but the read-back and the UI showed the old item | Acting through this path does not work. §5.2–5.8 are not built. The copilot instead shows the operation it *would* have performed as an instruction the player carries out by hand — a proposal card with no confirm button. Everything else in this design stands. |
| **C. Lua raised** | `RequestOperation` or `CityManager` absent or stubbed in `InGame` | As B. The findings record which binding, so nobody repeats the attempt without new information. |
| **D. Applied, read-back silent** | the UI showed the change but `GetCurrentProductionTypeHash` is absent or stubbed in `InGame` | §5 proceeds, with `requested_unconfirmed` as the only outcome an action can reach on the turn it is sent; `applied` is confirmed by the next poll's log row instead, and the card says so. |
| **E. Applied without validation** | the game accepted an item the settlement cannot build (no Campus, no Writing) and the queue shows it | §5 proceeds only with the guard the game lacks: the catalog restricts `item` to hashes present in this poll's `build_options` reading, and `CanStartOperation` — if present — runs in the chunk first. If `CanStartOperation` is also absent, acting is limited to exactly what the game itself offered that settlement this turn, and the spike's finding is quoted on the proposal card. |
| **F. The game misbehaved** | a crash, a desync, a stuck UI, a corrupted queue | Acting is dropped from this design. The findings record what happened. §3 and §4 are unaffected. |

The result is written to
`docs/research/2026-09-13-civ6-tuner-write-spike.md` before any acting task is
started, and the plan's acting tasks each begin by naming which outcome they
assume.

## 7. Provenance

Nothing new is invented. The copilot produces `EvidenceFact`s through the same
builders the decision layer uses — `yield_fact`, `ruleset_fact`,
`amenities_fact`, `build_option_fact` — so a fact the conversation cites has
the same id, kind, turn and note as the same fact in the evidence drawer of a
decision card. Generated prose is `generated: true` and labelled
*interpretation*; the deterministic answer is `generated: false`; the model
that wrote a piece of prose is displayed with it.

An action is not provenance and produces no fact (§5.8).

## 8. Honesty when things are off

Four things can be off, and each is said as itself:

- **No model** (`--no-llm`, or Ollama down): the box offers the catalog as
  buttons; every answer is deterministic and says so. Nothing pretends to
  understand the player's sentence.
- **No tuner**: every live question resolves to `Absence(tuner_absent)` with
  its `TunerUnavailable` cause — six after §4.6, each established rather than
  inferred. Acting is `not_sent` with the same cause.
- **No ruleset** (Civ VII, or an unreadable file): every ruleset question
  resolves to `Absence(ruleset_unavailable)` with the provider's reason.
- **Acting off** (the default): proposals are not offered; the act endpoint
  says which flag would enable it. The header carries no acting badge. When
  acting is on, the header says *Acting enabled for this run* for the whole
  run, so a player never forgets which kind of run they are in.

## 9. Security, stated plainly

Reads already run arbitrary Lua the program chose, over an unauthenticated
loopback socket the player opened. Acting sends Lua that changes the game.
Consequences:

- The catalog boundary holds in both directions: query Lua and command Lua
  are module constants; the only runtime values are validated integers the
  program read from the game itself; no player text is ever a parameter.
- The model chooses ids from enums. A schema violation is a rejected
  generation, not a sent command.
- The act endpoint is loopback-only by construction (`--allow-actions` refuses
  a non-loopback host), one-shot per proposal, turn-checked, and journaled
  before sending.
- The README's tuner section gains an acting subsection that says what the
  flag does, that the advisor cannot undo an action, that the journal is where
  to look afterwards, and that none of this changes what the open port already
  exposes to every local process.

## 10. Testing

- **Grounding** — table-driven tests of `check`: digits, decimals, percentages
  against ratios, thousands separators, negatives, number words, *one*
  excluded, citations stripped, numbers in notes admitted, numbers in the
  player's text not admitted as citations, a typed number repeated as the
  player's claim admitted, a typed number repeated while a cited figure goes
  unstated rejected, a player-report figure attributed or rejected, numbers
  with no citation rejected. Plus the
  existing `questions.validate` tests extended with an ungrounded number.
- **Isolation from the machine.** No default-suite test may depend on whether
  port 4318 is listening. Two shipped tests did — they asserted `NOT_ENABLED`
  after a bare refusal, and failed with a game at the menu — and are fixed by
  pointing the profile's tuner factory at a port that cannot be listening or
  injecting the provider, never by skipping when a socket is found. A test
  that passes only when the developer has no game open is not a test.
- **The flag** — `read_enable_tuner` against temporary files: `1`, `0`, no
  line, no `[Debug]` section, a commented-out line, an absent file, an
  unreadable file; and `open_tuner` against a refused port with each file
  state, asserting the cause and that the `EnableTuner 1` instruction appears
  only when the file says 0.
- **Catalog** — every entry declares its parameter kinds and a verified date;
  a parameter outside its set is `Absence(bad_parameter)` and never reaches a
  resolver; each resolver's facts carry the expected `SourceKind`; each
  absence names the real cause (the Civ VII profile's own reason; the tuner's
  own enum).
- **Ruleset growth** — each new table and column is read from the stand-in
  fixture *and*, when the real file is present, from it; a test opens the real
  installed database read-only and skips when it is absent, so a rename in a
  patch fails a developer's run rather than a player's.
- **Conversation** — select and compose schemas contain exactly this poll's
  enums; the fallback names every fact and every absence; a rejected
  generation is recorded with its reason; history numbers are not admitted.
- **Acting** — with the flag off, the endpoint is 403 and the read-side client
  has no `perform`; with it on, against a fake game replaying the spike's
  captures: a proposal renders the recorded Lua, a moved turn is `not_sent`,
  the recorded rejection is `rejected`, the recorded success is `applied`, an
  unwritable journal is `not_sent`, a second confirmation is refused.
- **Delivery** — through the HTTP payload, as the tuner plan learned to: a
  chat answer's evidence reaches `/api/copilot/ask`; a journal entry reaches
  `/api/copilot/journal`.
- **Live** — the read-only live suite is unchanged. A separate acting suite,
  in the same directory, is skipped unless `CIV_ADVISOR_LIVE_ACT=1` is set
  *and* the socket is up, so nobody running the existing live checks writes
  into their game by accident.

The default suite stays offline and fast. No new runtime dependency is needed:
the number rule is a regular expression and `decimal`, the journal is
`json` and `os.fsync`.

## 11. Scope

**In:** the conversation box and its two-phase grounded generation; the number
rule applied to all generated prose; the question catalog over logs, ruleset
and tuner; the ruleset allowlist growth in §4.2; the spike; and, if the spike
allows, one operation with proposals, per-action confirmation, the flag and
the journal.

**Out of this cut:** any second operation (units, districts, purchases,
research, civics) — each needs its own spike; anything Civ VII live or acting;
persisting the transcript; a model choosing among several operations; any
form of "confirm all". Reading the Saves folder for §5.7 was considered and
rejected as a false assurance.

## 12. Open questions for review

1. **Number words.** §4.3 admits *one* as a pronoun and treats *two* upward as
   numerals. The alternative — treating no words as numbers and relying on the
   prompt — is weaker; the alternative in the other direction — rejecting
   *one* — will reject ordinary prose. Recommendation: as written.
2. **The player's own numbers.** RESOLVED in review: a player report IS a
   citable fact. It is already a first-class source kind here, carrying a
   value, an `observed_turn` and a `reported_at` -- dated, labelled and
   stored, which is exactly the traceability the rule demands. Excluding it
   would have meant the copilot could not discuss the very figures the Refine
   flow exists to collect, which is a hole rather than rigour. The condition
   is attribution: prose citing a player report must say whose it is and when
   ("the 8 turns you reported on turn 59"), never state it unattributed as
   though the game had said it. The number rule is unchanged -- every number
   must still appear in a cited fact; a player report is now one of the kinds
   of fact it may appear in. Ruled again on the follow-up: a number that exists
   only in the text just typed into the box stays excluded as a citation -- it
   is their claim, may be repeated only as such, and a grounded figure that
   disagrees is stated beside it (rule 7).
3. **Save acknowledgement.** Once per sitting, journaled. Review may prefer
   once per action; it costs a click per proposal. Recommendation: per
   sitting.
