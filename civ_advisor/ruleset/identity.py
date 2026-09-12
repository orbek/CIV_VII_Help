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
    """The cheap key: size and modification time.

    Used to decide whether anything needs re-deriving, so the 18 MB hash runs when the
    file moves rather than on every lookup. It is not the identity — a figure is labelled
    with the digest, which is what makes it checkable. Not sufficient on its own either:
    a mod that changes a value without changing the byte count leaves size identical, and
    mtime resolution varies by filesystem, so a caller that must be sure re-hashes.
    """
    status = path.stat()
    return (status.st_size, status.st_mtime_ns)


def identify(path: Path) -> RulesetIdentity:
    """The file's full content digest, read in blocks rather than all at once.

    Whole-file SHA-256 rather than a sample: a mod can change one row anywhere in an
    18 MB file, and a partial hash would let that row's figures keep citing an identity
    that no longer describes them. This runs once per `stamp()` change, not per lookup —
    callers that hold a provider open across many lookups re-derive only when `stamp()`
    itself has moved, which is what keeps the full hash affordable.
    """
    size, mtime_ns = stamp(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(BLOCK), b""):
            digest.update(block)
    return RulesetIdentity(path=path, size=size, mtime_ns=mtime_ns,
                           digest=digest.hexdigest())


__all__ = ["identify", "stamp"]
