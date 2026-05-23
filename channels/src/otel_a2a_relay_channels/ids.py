"""4-character channel IDs from the dictatable alphabet.

The alphabet drops the visually and phonetically ambiguous characters from
base32/base58. Origin: agentic-os docs/dictatable-id-alphabet.md.
"""

import secrets

import fastapi

ID_ALPHABET = "ABCDEFGHJKMPQRSTUVWXYZ456789"
ID_LEN = 4


def new_id() -> str:
    """Return a fresh random 4-char ID from the dictatable alphabet."""
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LEN))


def norm_id(raw: str) -> str:
    """Normalize a path id to canonical form, or 404 if it cannot be one."""
    cid = raw.strip().upper()
    if len(cid) != ID_LEN or any(c not in ID_ALPHABET for c in cid):
        raise fastapi.HTTPException(status_code=404, detail="no such channel")
    return cid
