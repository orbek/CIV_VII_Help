"""Reviewed, packaged knowledge about each supported game's mechanics.

Deliberately small and deliberately offline. It holds where to look in game and which
article explains a mechanic — never what an option is worth, because no figure here has
been verified against an installed ruleset.
"""
from .catalog import Catalog, CatalogError, GuideEntry, load_catalog

__all__ = ["Catalog", "CatalogError", "GuideEntry", "load_catalog"]
