"""Load and validate the reviewed guide catalog.

The catalog is packaged data, read with `importlib.resources` so it works from an
installed wheel, and it is read without a network request: guidance has to work while the
player is offline mid-game. Checking that the URLs still resolve is a separate, explicit
maintenance command (`scripts/check_guides.py`) — an HTTP 200 is not a review, and a link
check date is not the game's version.

Three separate things are deliberately not conflated:

  link health          — does the URL resolve today? (the audit script's job)
  editorial review     — has someone read the article and written these steps? (`review_status`)
  ruleset compatibility— do its numbers apply to the installed game? (`supported_rulesets`)

An entry can be perfectly reachable, carefully reviewed, and still supply no number that
may be used, which is why no entry in this catalog carries a numeric effect at all.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from urllib.parse import unquote, urlparse

CATALOG_FILE = "guides.json"
DEFAULT_CATALOG_PACKAGE = "civ_advisor.knowledge.civ7"
SCHEMA_VERSION = 1

# Editorial review states, strongest first. Only NAVIGATION_REVIEWED may back an
# instruction; the others exist so an unreviewed or broken source stays visible instead
# of quietly becoming a recommendation.
NAVIGATION_REVIEWED = "navigation_reviewed"
LINK_ONLY = "link_only"
UNREACHABLE = "unreachable"
REVIEW_STATUSES = (NAVIGATION_REVIEWED, LINK_ONLY, UNREACHABLE)

# Publishers we will link to, and what marks a page as being about Civilization VII
# specifically rather than another title in the series.
ALLOWED_HOSTS = {
    "civilization.fandom.com": ("(civ7)",),
    "civilization.2k.com": ("/civ-vii/",),
}


class CatalogError(ValueError):
    """The packaged catalog is not usable. Raised at load time, never swallowed: shipping
    a malformed catalog must fail loudly rather than silently drop guidance."""


@dataclass(frozen=True)
class GuideEntry:
    """One reviewed reference, and exactly how far it may be relied on."""

    id: str
    game: str
    title: str
    publisher: str
    url: str                                # the current article
    reviewed_url: str | None                # a revision permalink, when one is obtainable
    section: str | None                     # only when the anchor was actually confirmed
    kind: str                               # "mechanic" | "item"
    mechanic_keys: tuple[str, ...]
    item_keys: tuple[str, ...]
    yields: tuple[str, ...]                 # which yields this is about, for reconciliation
    instructions: tuple[str, ...]
    prerequisites: tuple[str, ...]
    supported_rulesets: tuple[str, ...]     # empty means compatibility is UNKNOWN
    supported_ages: tuple[str, ...]         # empty means unknown, not "all"
    review_status: str
    reviewed_at: str
    notes: str
    attribution: str

    @property
    def instructive(self) -> bool:
        """Whether this entry may back a how-to. Reviewed steps and nothing else."""
        return self.review_status == NAVIGATION_REVIEWED and bool(self.instructions)

    @property
    def version_known(self) -> bool:
        """Whether any ruleset compatibility has been established. Nothing in the shipped
        catalog sets this, which is why every named-item action stays conditional."""
        return bool(self.supported_rulesets)

    def applies_to_age(self, age: str | None) -> bool | None:
        """True / False / None for unknown. An unknown Age is never treated as a match:
        the caller must offer a conditional or an inspection instead."""
        if not self.supported_ages:
            return None
        if age is None:
            return None
        return age in self.supported_ages


@dataclass(frozen=True)
class Catalog:
    revision: str
    entries: tuple[GuideEntry, ...]
    game: str = "civ7"

    def get(self, guide_id: str) -> GuideEntry | None:
        return next((e for e in self.entries if e.id == guide_id), None)

    def resolve(self, ids: tuple[str, ...]) -> tuple[GuideEntry, ...]:
        """Every named entry, or an error. A model or an advisor naming a guide id we do
        not ship must fail rather than render a link to nowhere."""
        missing = [i for i in ids if self.get(i) is None]
        if missing:
            raise KeyError(f"unknown guide ids: {', '.join(missing)}")
        return tuple(self.get(i) for i in ids)  # type: ignore[misc]

    def for_mechanic(self, key: str) -> tuple[GuideEntry, ...]:
        return tuple(e for e in self.entries if key in e.mechanic_keys)

    def for_item(self, item_key: str) -> tuple[GuideEntry, ...]:
        return tuple(e for e in self.entries if item_key in e.item_keys)

    def yields_for_item(self, item_key: str) -> tuple[str, ...]:
        """Which yields a build item is documented as serving.

        The single reviewed source for that association, so `production.ITEM_YIELDS` and
        the decision layer cannot drift into two contradictory rules tables.
        """
        for entry in self.for_item(item_key):
            if entry.yields:
                return entry.yields
        return ()

    @property
    def item_yields(self) -> dict[str, tuple[str, ...]]:
        return {item: self.yields_for_item(item)
                for entry in self.entries for item in entry.item_keys
                if self.yields_for_item(item)}


def _require(row: dict, field: str, entry_id: str):
    if field not in row:
        raise CatalogError(f"guide {entry_id}: missing {field}")
    return row[field]


def _check_url(url: str, entry_id: str, expected_game: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise CatalogError(f"guide {entry_id}: {url} is not https")
    markers = ALLOWED_HOSTS.get(parsed.netloc)
    if markers is None:
        raise CatalogError(f"guide {entry_id}: {parsed.netloc} is not an allowed publisher")
    if expected_game != "civ7":
        # No per-game path marker convention is defined for any game but Civ VII yet;
        # inventing one for civ6 now, before it has a single entry, would be a guess.
        return
    path = unquote(parsed.path).casefold()
    if not any(marker in path for marker in markers):
        # The wiki covers every game in the series under one host, so an article without
        # the Civ VII marker is about another title and would be actively misleading.
        raise CatalogError(f"guide {entry_id}: {url} is not identifiable as a Civ VII page")


def _entry(row: dict, expected_game: str) -> GuideEntry:
    entry_id = row.get("id", "<no id>")
    for field in ("game", "title", "publisher", "url", "kind", "review_status",
                  "reviewed_at", "notes", "attribution"):
        _require(row, field, entry_id)
    if row["game"] != expected_game:
        raise CatalogError(f"guide {entry_id}: game {row['game']!r} is not {expected_game}")
    if row["review_status"] not in REVIEW_STATUSES:
        raise CatalogError(f"guide {entry_id}: unknown review status {row['review_status']!r}")
    if row["kind"] not in ("mechanic", "item"):
        raise CatalogError(f"guide {entry_id}: unknown kind {row['kind']!r}")
    _check_url(row["url"], entry_id, expected_game)
    if row.get("reviewed_url"):
        _check_url(row["reviewed_url"], entry_id, expected_game)
    entry = GuideEntry(
        id=entry_id, game=row["game"], title=row["title"], publisher=row["publisher"],
        url=row["url"], reviewed_url=row.get("reviewed_url"), section=row.get("section"),
        kind=row["kind"],
        mechanic_keys=tuple(row.get("mechanic_keys", ())),
        item_keys=tuple(row.get("item_keys", ())),
        yields=tuple(row.get("yields", ())),
        instructions=tuple(row.get("instructions", ())),
        prerequisites=tuple(row.get("prerequisites", ())),
        supported_rulesets=tuple(row.get("supported_rulesets", ())),
        supported_ages=tuple(row.get("supported_ages", ())),
        review_status=row["review_status"], reviewed_at=row["reviewed_at"],
        notes=row["notes"], attribution=row["attribution"],
    )
    if entry.kind == "item" and not entry.item_keys:
        raise CatalogError(f"guide {entry_id}: an item guide must name its item keys")
    if entry.review_status != NAVIGATION_REVIEWED and entry.instructions:
        raise CatalogError(f"guide {entry_id}: only a reviewed entry may carry instructions")
    if entry.review_status == NAVIGATION_REVIEWED and not entry.instructions:
        raise CatalogError(f"guide {entry_id}: reviewed but carries no instructions")
    if row.get("effects") and not entry.supported_rulesets:
        # Nothing in the shipped catalog sets `effects`. This is the gate that keeps it
        # that way: an exact figure needs a ruleset it was verified against.
        raise CatalogError(f"guide {entry_id}: exact effects need a supported ruleset")
    return entry


def load_catalog(raw: str | None = None, package: str = DEFAULT_CATALOG_PACKAGE,
                  game: str | None = None) -> Catalog:
    """The packaged catalog. Offline; raises `CatalogError` if it is not usable.

    `game` names which game's entries are expected; `None` means "civ7", for every
    caller that predates other games. A catalog with no entries is valid ONLY when
    loading a package other than Civ VII's own: Civ VII must always ship at least
    one reviewed guide, but a brand-new game (Civ VI) legitimately has none yet, and
    an empty catalog is the honest way to say so rather than copying another game's
    guides.
    """
    expected_game = game if game is not None else "civ7"
    if raw is None:
        raw = resources.files(package).joinpath(CATALOG_FILE).read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CatalogError(f"guide catalog is not valid JSON: {exc}") from exc
    if data.get("schema_version") != SCHEMA_VERSION:
        raise CatalogError(f"guide catalog schema {data.get('schema_version')!r} "
                           f"is not {SCHEMA_VERSION}")
    revision = data.get("catalog_revision")
    if not revision:
        raise CatalogError("guide catalog has no catalog_revision")
    entries = tuple(_entry(row, expected_game) for row in data.get("entries", ()))
    ids = [e.id for e in entries]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise CatalogError(f"duplicate guide ids: {', '.join(sorted(duplicates))}")
    if not entries and package == DEFAULT_CATALOG_PACKAGE:
        raise CatalogError("guide catalog is empty")
    return Catalog(revision=revision, entries=entries, game=expected_game)


__all__ = ["Catalog", "CatalogError", "GuideEntry", "NAVIGATION_REVIEWED", "load_catalog"]
