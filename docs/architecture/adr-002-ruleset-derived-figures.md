# ADR-002: Figures read from an installed ruleset

Date: 2026-09-12
Status: proposed

## Context

Civilization VII gives the advisor no way to check a number. Its logs do not
record what a building yields or costs, and no packaged guide asserts a figure
verified against an installed ruleset — so the advisor asks the player to read
the game's own preview and records the answer as *your report*, dated to the
turn.

Civilization VI is different. It writes `Cache/DebugGameplay.sqlite`, the
compiled ruleset, 18 MB and 429 tables, queryable in under 20 ms. A Library
costs 90 production and 1 gold, needs a Campus and Writing, and yields a flat
+2 Science — each of those a plain indexed row.

Two problems follow. The database also contains an effect system whose numbers
are not numbers; and it identifies no version, so a figure from it cannot be
attributed to a ruleset by name.

## Decision

Read the plain rows. Refuse the effect system. Label with the file.

**Plain rows are stated as fact.** Building and district cost, maintenance,
prerequisites and flat yields; technology and civic cost, era and prerequisites;
eureka and inspiration percentages and triggers; unit cost, maintenance, combat
strength, prerequisites and upgrade target.

**The effect system is refused structurally, not by discipline.**
`Modifiers` -> `ModifierArguments` records that an effect fires, who it applies
to and what triggers it. Its magnitude is defined by an `EffectType` the
database does not catalogue: the Great Library's science modifier carries
`TechBoost=1`, where `1` is a flag meaning "apply the standard boost" and not a
quantity of science. Three mechanisms keep such a value from becoming a figure:

1. `READABLE_COLUMNS` is an allowlist of table-and-column pairs, and `_select`
   is the only place a statement is built. No effect table is in it.
2. `BuildingModifiers` — needed because an empty `Building_YieldChanges` result
   is not evidence that a building yields nothing — is reachable only through
   `_count`, which returns a row count and can carry no magnitude.
3. `RulesetFigure.__post_init__` requires a table, a column and a row key. A
   number with no row behind it cannot be constructed.

What an effect becomes instead is a `RulesetMention`, which has no value field
and renders as "this exists; the ruleset does not state its magnitude". A row
count that establishes an effect exists — never its size — is a `RulesetCount`,
which has no `value`/`unit` field either, so the count itself cannot be
mistaken for a yield or a cost.

**Provenance is the file, not a version.** `PRAGMA user_version` is 0 and no
Version, DLC, Mod or Ruleset table exists. `XP1`/`XP2` table-name suffixes imply
both expansions are compiled in, and that is an inference we do not publish. A
figure is labelled with the filename, the time the game last wrote it, and a
SHA-256 of its bytes — reproducible by the reader, and changed by any mod that
rewrites the ruleset. `RulesetIdentity` has no version field, so there is
nowhere for one to be added by accident.

## Trade-offs and consequences

- Civ VI recommendations get better figures than Civ VII ones, and the two games
  will visibly differ. That is a real capability divergence, and the UI says
  which source each figure came from rather than hiding it.
- A number the player can see in game — a policy card's effect, a government
  bonus, a wonder ability — will not be quoted here. Saying "the ruleset does
  not state this" about something visible on screen looks like a gap. It is the
  correct answer, and the alternative is an authoritative-looking guess.
- A cached provider is keyed on the file's identity, not just a cheap
  size/mtime proxy: dropping that proxy (review found it could miss a
  same-size edit) means every lookup re-derives the file's digest, verified
  again before and after the rows are read, so a stale figure is never served
  even by a provider that stays open across many rebuilds. A cache clear on a
  game switch closes what was opened rather than leaving it running against a
  game no longer on screen.
- Reading the player's own game file is a trust boundary. It is opened `mode=ro`
  with `PRAGMA query_only = 1`, and nothing in this package writes anywhere.
- `building()` (and its four siblings) return `None` for three different
  situations — no row, a closed provider, or a read that could not get a
  stable digest after several attempts — and do not distinguish the last two
  from each other. This is an argued decision, not an oversight; see
  `Civ6Ruleset._read_verified`'s docstring for why the ambiguity is judged
  narrow enough not to need a fourth state on every fact type.

## Revisit triggers

Reconsider the effect system only with a hand-built, versioned table of
`EffectType` argument semantics, validated against observed game behaviour and
shipped with its own review status — the same bar the guide catalog holds to.
Reconsider the version question if Firaxis ever writes an identity table.
Reconsider adjacency yields once the join from a district to its adjacency ids
has actually been verified against a real install. Reconsider the three-way
`None` if the "file could not hold still for three attempts" case turns out not
to be rare in practice.
