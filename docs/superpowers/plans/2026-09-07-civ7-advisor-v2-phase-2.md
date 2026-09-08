# Civ VII Advisor v2 — Phase 2 Local Ollama Commentary

Status: in progress on `feature/v2-tactical-intel` after Phase 1b commit `a7825c8`.

1. Add local-only Ollama client, response types, compact prompt builder, and validation tests using `httpx.MockTransport`.
2. Add one background worker with a per-complete-turn cache; Store rebuilds must never wait for generation.
3. Add CLI model controls and `/api/commentary`, including failure states and server-side fair-mode hiding.
4. Render second opinion, top-insight explanations, and an ordered turn plan as inert text.
5. Document how to run Ollama, run focused/full tests, review the integration, and commit.
