# Civ VII Advisor v2 — Phase 1b Tactical Intelligence

Status: in progress on `feature/v2-tactical-intel`.

1. Pin the eight live tactical log formats in `tests/fixtures/logs_v2` and document the observed row shapes.
2. Add isolated readers for unit operations, tactical moves/attacks, operations, combat orders, operation odds, unit efficiency, mayhem, and commander promotions.
3. Build typed tactical state and verify the game's skewed axial hex distance/orientation.
4. Add the Oracle-only tactical advisor: nearby enemies, attacks on human tiles, matchup guidance, operation odds, and exposed human units.
5. Add `/api/tactical`, with server-side Oracle gating, and render a compact SVG tactical map in Intel.
6. Run focused and full tests, browser-check both Oracle modes, update the progress ledger, and commit the phase.
