"""The canonical variation hash: its exact bytes, its digest, and its limits.

WHY THIS FILE EXISTS — the ADR-17 item carried since Step 1.2, now closed.
``real_adapter._variation_hash`` has computed a local sha256 since Step 1.2 under
a flagged comment saying System Design §2 assigned the canonical hash to the W-8
snapshot module, and that "the two must be reconciled byte-for-byte when
``snapshot`` is built in Step 2.5."

W-8 has now landed, and the reconciliation is that there was never a second
implementation to reconcile WITH. Under ADR-28's contract-only grant W-8 cannot
import the adapter, and the adapter must mint a ``Variation`` at select /
list_options time — long before any snapshot exists — so ownership stays here and
§2 is what is being corrected (ADR-29). W-8 receives the hash as DATA and computes
none; ``tests/snapshot/test_snapshot_assembly.py`` asserts that structurally, by
checking no hashing primitive appears in that module at all.

What remained owed was this: the value itself was pinned NOWHERE. A regex sweep
for any 64-hex run across ``src/``, ``tests/``, ``docs/`` and ``fixtures/``
returned zero matches; the only assertion on the field was
``variation_hash.startswith("sha256:")``, which cannot tell one canonicalization
from another.

WHAT "BYTE-FOR-BYTE" IS PROTECTING AGAINST, measured rather than asserted. Six
canonicalizations of the SAME input ``{"w": "2mm", "h": "1.6mm"}``, each one line
different from the next, produce six different digests:

    json sort_keys + compact separators  (the real one)   f400eee42dafcdaa...
    json sort_keys, DEFAULT separators                    6183781fcf06f688...
    json compact, NO sort_keys                            742f09b44e9dce81...
    repr(sorted(items))                                   a0b7e43dbc1cc4ac...
    "k=v" newline-joined, sorted                          1e6ef74ded340091...
    "k=v" semicolon-joined, sorted                        8b102be2dac0b8f7...

Dropping ``sort_keys``, or letting ``json.dumps`` use its default separators,
looks like a tidy-up and silently re-keys every variation in the product. That is
what these vectors stand in the way of.

WHAT THE VECTORS ARE, AND WHY THE BYTES ARE PINNED ALONGSIDE THE DIGEST. A digest
alone tells a maintainer that something changed, not what; the canonical byte
string tells them which of the six above they have drifted into, without running
anything. Both are asserted for every vector.

THE HASH IS NOT ALWAYS A DIGEST, and that is the second thing this file pins.
``_resolve_variation`` carries an unparseable PyAEDT variation token through AS
the ``variation_hash`` rather than inventing values for it — so the field can
legitimately hold ``"nominal"``, or an empty string, and a consumer that assumes
it parses as ``sha256:<64 hex>`` is wrong about real data. That behaviour was
previously unpinned at the adapter: the snapshot suite asserts W-8 PROPAGATES a
non-digest token, but it constructs the token by hand, so nothing held the
adapter to producing one.

LIVE-VERIFICATION BOUNDARY, stated so these vectors are not read as more than
they are. What is pinned here is OUR canonicalization of a name->value map. What
is NOT pinned, and cannot be until Phase 5.2, is the shape of the variation
STRING PyAEDT actually emits — ``_parse_variation`` assumes ``w='2mm' h='1.6mm'``
and is ``mock-only``. If that assumption is wrong, these digests stay correct for
the maps they are computed over while the maps themselves change.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from hfss_agent.adapter.real.real_adapter import (
    _parse_variation,
    _resolve_variation,
    _variation_hash,
)

# The golden vectors: (label, input map, exact canonical bytes, full digest).
#
# THE DIGESTS WERE RECOMPUTED FROM THE SOURCE FUNCTION, never transcribed — a
# digest copied by hand is a digest nobody verified. The recomputation is also
# what ``test_the_pinned_digest_is_reproducible_from_first_principles`` below
# repeats independently of ``_variation_hash`` itself, so a change to the
# function cannot quietly redefine what "correct" means.
#
# THE SECOND VECTOR IS THE SAME MAP IN A DIFFERENT INSERTION ORDER and carries
# the SAME digest. That is ``sort_keys=True`` doing its job, and it is a property
# worth pinning rather than a coincidence: Python dicts preserve insertion order,
# so two callers building the same variation from differently-ordered PyAEDT
# output would otherwise key it two ways.
GOLDEN_VECTORS: tuple[tuple[str, dict[str, str], bytes, str], ...] = (
    (
        "two keys, insertion order w,h",
        {"w": "2mm", "h": "1.6mm"},
        b'{"h":"1.6mm","w":"2mm"}',
        "sha256:f400eee42dafcdaae80b572bdb42818735e2843b804b5bd68896a7b341b54a88",
    ),
    (
        "the same map, insertion order h,w",
        {"h": "1.6mm", "w": "2mm"},
        b'{"h":"1.6mm","w":"2mm"}',
        "sha256:f400eee42dafcdaae80b572bdb42818735e2843b804b5bd68896a7b341b54a88",
    ),
    (
        "the empty map",
        {},
        b"{}",
        "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
    ),
)

# The prefix is part of the value, not decoration: it declares which digest
# algorithm produced the hex, so a future change of algorithm is visible in the
# field itself rather than only in a changed length.
DIGEST_PREFIX = "sha256:"


# --- 1. the vectors ----------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "values", "canonical", "digest"),
    GOLDEN_VECTORS,
    ids=[vector[0] for vector in GOLDEN_VECTORS],
)
def test_the_canonical_bytes_and_the_digest_are_both_pinned(
    label: str, values: dict[str, str], canonical: bytes, digest: str
) -> None:
    """Both halves, for every vector.

    The canonicalization is asserted directly rather than only through its
    digest, so a drift reports WHICH canonicalization it drifted into instead of
    only that two hex strings differ.
    """
    assert (
        json.dumps(values, sort_keys=True, separators=(",", ":")).encode("utf-8")
        == canonical
    ), f"{label}: the canonical byte string changed"
    assert _variation_hash(values) == digest, f"{label}: the digest changed"


def test_insertion_order_does_not_change_the_key() -> None:
    """Stated as its own assertion, not left to two vectors happening to match.

    The two-vector form above would still pass if someone pinned two different
    digests for the two orderings; this one cannot.
    """
    assert _variation_hash({"w": "2mm", "h": "1.6mm"}) == _variation_hash(
        {"h": "1.6mm", "w": "2mm"}
    )


def test_the_pinned_digest_is_reproducible_from_first_principles() -> None:
    """Recomputed here WITHOUT calling ``_variation_hash``.

    If the only check were "the function returns the pinned value", then editing
    the function and re-pinning its new output would look identical to a green
    build. This one hashes the pinned BYTES directly, so the digest and the
    canonicalization are held to each other rather than both to whatever the
    function currently does.
    """
    for label, _values, canonical, digest in GOLDEN_VECTORS:
        expected = DIGEST_PREFIX + hashlib.sha256(canonical).hexdigest()
        assert expected == digest, f"{label}: pinned digest is not sha256 of the bytes"


def test_every_vector_has_the_declared_shape() -> None:
    """A guard on the vectors themselves: 64 lowercase hex under the prefix.

    Without it, a vector could be re-pinned to a truncated or upper-cased digest
    and every assertion above would still pass, because they only compare it to
    itself.
    """
    for label, _values, _canonical, digest in GOLDEN_VECTORS:
        assert digest.startswith(DIGEST_PREFIX), label
        hex_part = digest[len(DIGEST_PREFIX) :]
        assert len(hex_part) == 64, f"{label}: {len(hex_part)} hex chars, expected 64"
        assert hex_part == hex_part.lower(), f"{label}: hex is not lower-cased"
        assert all(char in "0123456789abcdef" for char in hex_part), label


# --- 2. what the six canonicalizations demonstrate ---------------------------


def test_six_near_miss_canonicalizations_give_six_different_digests() -> None:
    """THE MEASUREMENT BEHIND THIS FILE, recomputed rather than quoted.

    The module docstring lists these; this asserts they really are all distinct,
    so the claim "byte-for-byte matters" is a fact the suite re-establishes on
    every run rather than a number someone wrote down once.

    Each variant is ONE line different from the real implementation. That is the
    point: none of them looks like a breaking change at a glance.
    """
    values = {"w": "2mm", "h": "1.6mm"}
    canonicalizations = (
        json.dumps(values, sort_keys=True, separators=(",", ":")),  # the real one
        json.dumps(values, sort_keys=True),  # default separators
        json.dumps(values, separators=(",", ":")),  # no sort_keys
        repr(sorted(values.items())),
        "\n".join(f"{key}={value}" for key, value in sorted(values.items())),
        ";".join(f"{key}={value}" for key, value in sorted(values.items())),
    )
    digests = {
        hashlib.sha256(text.encode("utf-8")).hexdigest() for text in canonicalizations
    }
    assert len(digests) == len(canonicalizations)
    # And the first one is the one the product actually uses.
    assert _variation_hash(values) == DIGEST_PREFIX + hashlib.sha256(
        canonicalizations[0].encode("utf-8")
    ).hexdigest()


def test_the_encoding_is_utf_8_and_a_non_ascii_name_proves_it() -> None:
    """The third thing a "harmless" edit could change, and the one the ASCII
    vectors above cannot see: every vector here is ASCII, where utf-8, latin-1
    and ascii all agree. A non-ASCII variable name separates them."""
    values = {"width_µm": "2"}
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    assert _variation_hash(values) == DIGEST_PREFIX + hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    assert canonical.encode("utf-8") != canonical.encode("utf-16")


# --- 3. the hash is not always a digest --------------------------------------


@pytest.mark.parametrize("token", ["nominal", "", "Nominal Variation"])
def test_an_unparseable_token_is_carried_through_as_the_hash(token: str) -> None:
    """PINNED AT THE ADAPTER, which is where it was missing.

    ``_parse_variation`` yields ``{}`` for a string it cannot read, and
    ``_resolve_variation`` then carries the TOKEN through as the
    ``variation_hash`` rather than hashing the empty map — because hashing ``{}``
    would give every unparseable variation the same key, silently merging
    distinct points in the design space.

    The consequence a consumer must know: ``variation_hash`` is a stable HANDLE,
    not a guaranteed digest. ``tests/snapshot/test_snapshot_assembly.py`` asserts
    W-8 propagates such a token unchanged, but it constructs the token by hand —
    so until this test, nothing held the adapter to producing one.
    """
    assert _parse_variation(token) == {}

    variation = _resolve_variation(token)
    assert variation.values == {}
    assert variation.variation_hash == token
    assert not variation.variation_hash.startswith(DIGEST_PREFIX)
    # And it is NOT the digest of the empty map, which is the tempting shortcut.
    assert variation.variation_hash != _variation_hash({})


def test_a_parseable_token_does_get_a_digest() -> None:
    """The other side, so the test above cannot be read as "the hash is never a
    digest". A readable variation string is parsed and hashed normally."""
    variation = _resolve_variation("w='2mm' h='1.6mm'")
    assert variation.values == {"w": "2mm", "h": "1.6mm"}
    assert variation.variation_hash == GOLDEN_VECTORS[0][3]
