"""The reviewed guide catalog: offline, validated, and unable to assert a rule it has
not established. These tests never touch the network — link auditing is
`scripts/check_guides.py`, run by hand."""
from __future__ import annotations

import json
from importlib import resources

import pytest

from civ_advisor.knowledge.catalog import (
    NAVIGATION_REVIEWED,
    Catalog,
    CatalogError,
    load_catalog,
)

MINIMAL = {
    "id": "guide.x", "game": "civ7", "title": "X", "publisher": "P",
    "url": "https://civilization.fandom.com/wiki/X_%28Civ7%29", "kind": "mechanic",
    "review_status": "link_only", "reviewed_at": "2026-09-08", "notes": "", "attribution": "",
}


def catalog_with(*entries: dict) -> Catalog:
    return load_catalog(json.dumps({
        "schema_version": 1, "catalog_revision": "test", "entries": list(entries)}))


def test_the_packaged_catalog_loads_without_a_network_request(monkeypatch):
    """Guidance has to work mid-game with no connection, so loading must not reach out."""
    import httpx

    def refuse(*a, **k):
        raise AssertionError("loading the catalog must not make a request")

    monkeypatch.setattr(httpx, "get", refuse)
    monkeypatch.setattr(httpx.Client, "request", refuse)
    catalog = load_catalog()
    assert catalog.revision and catalog.entries
    assert all(e.game == "civ7" for e in catalog.entries)


def test_every_shipped_entry_that_backs_instructions_has_been_reviewed():
    for entry in load_catalog().entries:
        if entry.instructions:
            assert entry.review_status == NAVIGATION_REVIEWED, entry.id
            assert entry.attribution, entry.id
            assert entry.reviewed_at, entry.id


def test_no_shipped_entry_supplies_a_numeric_effect():
    """The catalog's central promise. No figure here was verified against an installed
    ruleset, so every figure in a recommendation must come from the player's own preview."""
    raw = json.loads(resources.files("civ_advisor.knowledge.civ7")
                     .joinpath("guides.json").read_text(encoding="utf-8"))
    for row in raw["entries"]:
        assert "effects" not in row, row["id"]
        for text in row.get("instructions", []):
            assert not any(ch.isdigit() for ch in text.replace("1.2.5", "")), row["id"]


def test_the_culture_pilot_can_resolve_the_guides_it_needs():
    catalog = load_catalog()
    assert [e.id for e in catalog.for_mechanic("culture")]
    monument = catalog.for_item("BUILDING_MONUMENT")
    amphitheater = catalog.for_item("BUILDING_AMPHITHEATER")
    assert len(monument) == 1 and len(amphitheater) == 1
    assert monument[0].instructive and amphitheater[0].instructive
    # The workflow itself comes from the publisher's own documentation.
    workflow = catalog.get("guide.official.settlements")
    assert workflow.instructive and workflow.publisher.startswith("2K")
    assert "placement" in workflow.mechanic_keys
    assert catalog.resolve(("guide.culture", "guide.building.monument"))


def test_ruleset_compatibility_is_separate_from_review_and_from_link_health():
    catalog = load_catalog()
    monument = catalog.get("guide.building.monument")
    # Reviewed, and still unable to supply a version-dependent figure.
    assert monument.instructive and not monument.version_known
    # An unknown Age is never a match; the caller must offer a conditional or inspection.
    assert monument.applies_to_age("AGE_ANTIQUITY") is None
    assert monument.applies_to_age(None) is None
    workflow = catalog.get("guide.official.settlements")
    assert workflow.version_known and workflow.supported_rulesets == ("update-1.2.5-or-later",)
    assert workflow.applies_to_age("AGE_ANTIQUITY") is None      # Ages still unknown


def test_the_catalog_is_the_single_source_for_item_yields():
    """Phase 3 reconciles production.ITEM_YIELDS against this rather than keeping two
    contradictory rules tables. Pin that the overlap agrees today."""
    from civ_advisor.advisors import production

    catalog = load_catalog()
    for item, yields in catalog.item_yields.items():
        assert production.ITEM_YIELDS.get(item) in yields, item


def test_a_non_civ_vii_article_is_rejected():
    """One wiki host covers the whole series. An article about another title would be
    actively misleading, so the marker in the path is required."""
    with pytest.raises(CatalogError, match="not identifiable as a Civ VII page"):
        catalog_with(MINIMAL | {"url": "https://civilization.fandom.com/wiki/Culture_(Civ6)"})
    with pytest.raises(CatalogError, match="is not civ7"):
        catalog_with(MINIMAL | {"game": "civ6"})


def test_an_unknown_publisher_or_insecure_url_is_rejected():
    with pytest.raises(CatalogError, match="not an allowed publisher"):
        catalog_with(MINIMAL | {"url": "https://example.com/wiki/Culture_%28Civ7%29"})
    with pytest.raises(CatalogError, match="not https"):
        catalog_with(MINIMAL | {"url": "http://civilization.fandom.com/wiki/Culture_%28Civ7%29"})


def test_malformed_entries_are_rejected_loudly():
    with pytest.raises(CatalogError, match="missing title"):
        catalog_with({k: v for k, v in MINIMAL.items() if k != "title"})
    with pytest.raises(CatalogError, match="unknown review status"):
        catalog_with(MINIMAL | {"review_status": "looks_fine"})
    with pytest.raises(CatalogError, match="must name its item keys"):
        catalog_with(MINIMAL | {"kind": "item"})
    with pytest.raises(CatalogError, match="duplicate guide ids"):
        catalog_with(MINIMAL, MINIMAL)
    with pytest.raises(CatalogError, match="not valid JSON"):
        load_catalog("{")
    with pytest.raises(CatalogError, match="schema"):
        load_catalog(json.dumps({"schema_version": 99, "entries": []}))
    with pytest.raises(CatalogError, match="no catalog_revision"):
        load_catalog(json.dumps({"schema_version": 1, "entries": [MINIMAL]}))
    with pytest.raises(CatalogError, match="is empty"):
        load_catalog(json.dumps({"schema_version": 1, "catalog_revision": "t", "entries": []}))


def test_an_unreviewed_entry_cannot_carry_instructions():
    with pytest.raises(CatalogError, match="only a reviewed entry may carry instructions"):
        catalog_with(MINIMAL | {"instructions": ["do the thing"]})
    with pytest.raises(CatalogError, match="reviewed but carries no instructions"):
        catalog_with(MINIMAL | {"review_status": NAVIGATION_REVIEWED})


def test_exact_effects_require_a_ruleset_they_were_verified_against():
    with pytest.raises(CatalogError, match="exact effects need a supported ruleset"):
        catalog_with(MINIMAL | {"effects": {"culture": 3}})
    assert catalog_with(MINIMAL | {"effects": {"culture": 3},
                                   "supported_rulesets": ["update-1.2.5"]}).entries


def test_naming_a_guide_the_catalog_does_not_ship_is_an_error():
    """The model picks from supplied ids; it cannot invent a link. An unknown id must
    fail rather than render."""
    with pytest.raises(KeyError, match="unknown guide ids: guide.invented"):
        load_catalog().resolve(("guide.culture", "guide.invented"))


def test_catalog_is_loaded_from_the_package_the_profile_names():
    """The guides a game gets must follow from its profile, not from a constant,
    or a second game would silently be handed Civ VII's catalog."""
    from civ_advisor.games.civ7 import CIV7

    catalog = load_catalog(package=CIV7.knowledge_package)

    assert catalog.entries
    assert {e.game for e in catalog.entries} == {"civ7"}
