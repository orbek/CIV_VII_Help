#!/usr/bin/env python
"""Audit the guide catalog's links. A developer maintenance command, run by hand.

This is deliberately not a test and never runs during play:

  - It makes network requests, and the advisor must work offline mid-game.
  - It checks *link health only*. An HTTP 200 says a page exists; it says nothing about
    whether the article still supports the instructions we wrote from it, and nothing
    about whether its numbers match the installed ruleset. A green run is not a review.
  - It never rewrites `guides.json`. It reports what a human should look at. Silently
    replacing packaged, reviewed rules with whatever a page says today is exactly the
    failure mode this separation exists to prevent.

Usage:
    uv run python scripts/check_guides.py [--timeout 20] [--json]

Exit status is 1 if any entry that currently backs an instruction is unreachable or has
moved, so it can be wired into a release checklist.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass

import httpx

from civ_advisor.games.registry import get_profile
from civ_advisor.knowledge.catalog import UNREACHABLE, load_catalog

USER_AGENT = "civ7-advisor guide-audit (link health check; contact via repository)"


@dataclass
class Result:
    id: str
    url: str
    review_status: str
    instructive: bool
    status: str          # "ok" | "moved" | "blocked" | "gone" | "error"
    http_status: int | None
    final_url: str | None
    detail: str

    @property
    def blocking(self) -> bool:
        """Whether this needs attention before a release.

        An entry already recorded as unreachable is a known gap, not a regression: it
        backs no instruction, and the catalog says so. "blocked" is not a regression
        either — the publisher refused an automated request, which says nothing about
        the page — but it is reported so a human knows this URL cannot be audited here.
        """
        if self.review_status == UNREACHABLE:
            return False
        return self.instructive and self.status not in ("ok", "blocked")


def check(url: str, client: httpx.Client) -> tuple[str, int | None, str | None, str]:
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        return "error", None, None, f"{type(exc).__name__}: {exc}"
    final = str(response.url)
    if response.status_code in (401, 403, 405, 429) or response.status_code >= 500:
        # The publisher refused or throttled an automated request. That is a fact about
        # this client, not about the page: calling it "gone" would be false, and acting
        # on it by dropping a reviewed guide would lose working guidance.
        return ("blocked", response.status_code, final,
                f"HTTP {response.status_code}: the publisher refused an automated request. "
                "Open the URL in a browser to check it; this script cannot.")
    if response.status_code >= 400:
        return "gone", response.status_code, final, f"HTTP {response.status_code}"
    if final.rstrip("/") != url.rstrip("/"):
        return "moved", response.status_code, final, f"redirected to {final}"
    return "ok", response.status_code, final, "reachable; content NOT reviewed by this check"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--game", default="civ7", help="which game's catalog to audit")
    args = parser.parse_args(argv)

    profile = get_profile(args.game)
    catalog = load_catalog(package=profile.knowledge_package, game=profile.id)
    results: list[Result] = []
    with httpx.Client(timeout=args.timeout, follow_redirects=True,
                      headers={"User-Agent": USER_AGENT}) as client:
        for entry in catalog.entries:
            for url in filter(None, (entry.url, entry.reviewed_url)):
                status, code, final, detail = check(url, client)
                results.append(Result(entry.id, url, entry.review_status, entry.instructive,
                                      status, code, final, detail))

    blocking = [r for r in results if r.blocking]
    if args.json:
        print(json.dumps({"catalog_revision": catalog.revision,
                          "results": [asdict(r) for r in results],
                          "blocking": [r.id for r in blocking]}, indent=2))
    else:
        print(f"catalog {catalog.revision} — {len(results)} link(s) checked\n")
        for r in results:
            flag = "!!" if r.blocking else ("  " if r.status == "ok" else " ?")
            print(f"{flag} {r.status:6} {r.id}\n     {r.url}\n     {r.detail}")
        print("\nLink health only. This run does not review any article's contents and "
              "does not establish ruleset compatibility for any figure.")
        refused = [r for r in results if r.status == "blocked"]
        if refused:
            print(f"\n{len(refused)} link(s) could not be audited: the publisher refuses "
                  "automated requests. Check those by hand; do not treat them as broken.")
        if blocking:
            print(f"\n{len(blocking)} link(s) backing live instructions need a human review.")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
