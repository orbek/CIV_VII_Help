# ADR-001: Structured decisions with a local guide catalog

Date: 2026-09-08  
Status: proposed

## Context

The companion has deterministic log-derived insights, optional local Ollama commentary, and a small FastAPI/vanilla-JavaScript UI. The player needs a compact decision flow and guide-linked instructions that account for the current save. Logs do not comprehensively describe build availability, local placement previews, current ruleset, or all human choices. Current generated citations establish reference identity, not factual correctness.

The intended scale is a local, single-player second screen in the existing repository. No new hosting or distributed infrastructure is needed. The [implementation plan](../superpowers/plans/2026-09-08-civ7-companion-decision-ui.md) defines delivery and tests.

## Options considered

| Option | Benefit | Cost / failure mode |
| --- | --- | --- |
| Add guide URLs to existing prose | Smallest UI change | Does not answer which action fits the player's state or expose missing prerequisites. |
| Let Ollama browse and invent a build plan each turn | Broad coverage in principle | Slow/network-dependent; unsupported availability, version mixtures, and invented links become likely. |
| Scrape/index the whole wiki for retrieval | Broad document search | Adds ingestion, maintenance, and licensing complexity before validating usefulness; retrieval alone cannot establish what the current save permits. |
| Structured deterministic action candidates plus a small reviewed local guide catalog | Fast, testable prerequisites and links; usable without Ollama/network | Requires explicit mechanic coverage and context adapters. Unknown details need an inspection or player input. |

## Decision

Propose structured decisions assembled from coherent, dated snapshots. Use a reviewed local guide catalog, starting with culture and expanding to all promoted recommendation families. The application owns evidence, prerequisites, calculations, steps, and URLs. Ollama provides clearly labeled contextual explanation using supplied IDs. A small player-context panel fills decision-changing gaps and records its inputs as dated player reports.

Retain the existing web stack and insight interfaces while migrating. Publish one revisioned briefing payload and apply provenance filtering before it reaches the model, browser, or future memory. Start persistence only in the later priorities/history phase, using a small versioned local store scoped to game/session identity.

Player submissions and generated commentary share explicit session, mode, and revision contracts. Revalidate or reject stale submissions; attach explanations only to matching context. Guide entries retain both canonical links and reviewed revision permalinks where available, so mutable web pages do not silently change the application's local rules.

## Rationale

- The reported experience needs fewer steps between a warning and a useful decision.
- The player explicitly wants practical guide links tied to the current game state.
- Local inference and offline advice are existing product constraints.
- Availability and placement cannot be proven by a general guide or valid insight citation.
- Culture offers a narrow, testable first case using existing yield, queue, treasury, and threat data.

## Trade-offs and consequences

- Early coverage is curated rather than encyclopedic; unsupported actions remain observations or targeted inspections.
- More explicit data structures require a staged migration, but enable evidence navigation, predictable tests, and safe mode changes.
- Manual context introduces some player effort. Ask only for details that change the decision, show their origin, and expire them when the context changes.
- Catalog review has an ongoing cost. Keep link health separate from ruleset compatibility, and never refresh mechanics silently while a turn is being interpreted.
- A single revisioned response simplifies coherence, but source rows retain their own dates because human queues and completed-turn statistics legitimately differ.

## Revisit triggers

Reconsider broad retrieval after contextual questions demonstrate repeated needs outside the catalog. Reconsider a larger persistence layer when real history volume or save-branch requirements exceed the simple store. Reconsider a UI framework only if component complexity demonstrably impedes tested interactions. New reliable log sources can replace manual context one field at a time.
