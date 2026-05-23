"""Pure tests for the dictatable-id generator + validator."""

from __future__ import annotations

import fastapi
import pytest
from otel_a2a_relay_channels import ID_ALPHABET, ID_LEN, new_id, norm_id


def test_new_id_shape() -> None:
    for _ in range(200):
        cid = new_id()
        assert len(cid) == ID_LEN
        assert all(c in ID_ALPHABET for c in cid)


def test_id_alphabet_is_unambiguous() -> None:
    for bad in ["I", "L", "O", "1", "0", "N", "2", "3"]:
        assert bad not in ID_ALPHABET


def test_norm_id_uppercases_valid() -> None:
    valid = new_id().lower()
    assert norm_id(valid) == valid.upper()
    assert norm_id(f"  {valid}  ") == valid.upper()


@pytest.mark.parametrize("bad", ["", "AB", "ABCDE", "ABC!", "abc1", "....", "ABO0"])
def test_norm_id_rejects_malformed(bad: str) -> None:
    with pytest.raises(fastapi.HTTPException):
        norm_id(bad)
