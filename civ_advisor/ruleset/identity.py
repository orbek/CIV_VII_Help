"""Which file a figure came from, hashed so the claim can be checked.

The database names no game version, no DLC and no mods, so this is the strongest honest
statement available: this exact file, this many bytes, written at this time, with this
digest. A reader can re-run the hash; a mod that rewrites the ruleset changes it.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .base import RulesetIdentity

BLOCK = 1 << 20


def stamp(path: Path) -> tuple[int, int]:
    """A cheap, deliberately imperfect key: size and modification time.

    `open_ruleset` uses this to decide whether a *whole provider* is worth reopening
    across separate calls (a coarse, infrequent decision) — not to decide whether any
    single figure is safe to trust. It is not sufficient for that on its own: a mod that
    changes a value without changing the byte count leaves size identical, and mtime
    resolution varies by filesystem, so a piece of code that must be sure re-hashes with
    `identify` instead. This function makes no promise that a changed file always
    produces a changed stamp — only that a changed stamp always means a changed file.
    """
    status = path.stat()
    return (status.st_size, status.st_mtime_ns)


def identify(path: Path) -> RulesetIdentity:
    """The file's full content digest, read in blocks rather than all at once.

    Whole-file SHA-256 rather than a sample: a mod can change one row anywhere in an
    18 MB file, and a partial hash would let that row's figures keep citing an identity
    that no longer describes them.

    Measured against a real 18.1 MB installed database: this call costs about 15 ms.
    `Civ6Ruleset` calls it on every lookup rather than gating it behind `stamp()` --
    that measurement is why: 15 ms is affordable for an interactive advisor that
    rebuilds on a poll tick, and a cheap gate that can silently miss a same-size or
    coarse-mtime edit is not a trade worth making for it.
    """
    size, mtime_ns = stamp(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(BLOCK), b""):
            digest.update(block)
    return RulesetIdentity(path=path, size=size, mtime_ns=mtime_ns,
                           digest=digest.hexdigest())


__all__ = ["identify", "stamp"]
