"""4-character channel IDs from the dictatable alphabet.

The alphabet drops the visually and phonetically ambiguous characters from
base32/base58. Origin: agentic-os docs/dictatable-id-alphabet.md.
"""

import secrets

import fastapi

ID_LETTERS = "ABCDEFGHJKMPQRSTUVWXYZ"
ID_DIGITS = "456789"
ID_ALPHABET = ID_LETTERS + ID_DIGITS
ID_LEN = 4
ID_LETTER_LEN = 2


def new_id() -> str:
    """Return a fresh random ID: 2 dictatable letters then 2 dictatable digits."""
    letters = "".join(secrets.choice(ID_LETTERS) for _ in range(ID_LETTER_LEN))
    digits = "".join(secrets.choice(ID_DIGITS) for _ in range(ID_LEN - ID_LETTER_LEN))
    return letters + digits


def norm_id(raw: str) -> str:
    """Normalize a path id to canonical form, or 404 if it cannot be one."""
    cid = raw.strip().upper()
    if (
        len(cid) != ID_LEN
        or any(c not in ID_LETTERS for c in cid[:ID_LETTER_LEN])
        or any(c not in ID_DIGITS for c in cid[ID_LETTER_LEN:])
    ):
        raise fastapi.HTTPException(status_code=404, detail="no such channel")
    return cid
