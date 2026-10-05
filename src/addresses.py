"""
addresses.py
============

Compare street addresses written in different styles, e.g. the sheet's
``100 Maple Court`` with Google Maps' ``100 Maple Ct``.
"""

import re

# Street words and their abbreviations; both forms normalise to the same token.
_ABBREVIATIONS = {
    "avenue": "ave",
    "boulevard": "blvd",
    "circle": "cir",
    "court": "ct",
    "drive": "dr",
    "highway": "hwy",
    "lane": "ln",
    "parkway": "pkwy",
    "place": "pl",
    "road": "rd",
    "square": "sq",
    "street": "st",
    "terrace": "ter",
    "trail": "trl",
    "north": "n",
    "south": "s",
    "east": "e",
    "west": "w",
}


def normalize_street(address: str) -> str:
    """Normalise the street part of an address for comparison.

    Only the part before the first comma is used, so ``"100 Maple Ct,
    Fairfax, VA 22030"`` and ``"100 Maple Court"`` both become
    ``"100 maple ct"``.
    """
    street = address.split(",")[0].lower().replace("'", "").replace("’", "")
    tokens = re.sub(r"[^a-z0-9]+", " ", street).split()
    return " ".join(_ABBREVIATIONS.get(t, t) for t in tokens)


def same_street_address(a: str, b: str) -> bool:
    """True if two addresses have the same house number and street."""
    na, nb = normalize_street(a), normalize_street(b)
    return bool(na) and na == nb
