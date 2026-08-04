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

WHAT "BYTE-FOR-BYTE" IS PROTECTING AGAINST, measured rather than asserted. Seven
canonicalizations of the SAME input ``{"width_µm": "2", "h": "1.6mm"}``, each one
line different from the next, produce seven different digests:

    json sort_keys + compact separators  (the real one)   06f3009c529bdd65...
    json sort_keys, DEFAULT separators                    22d2a5fd6d9f448e...
    json compact, NO sort_keys                            546b504a65a2ef37...
    repr(sorted(items))                                   67b0c6d4ea915b13...
    "k=v" newline-joined, sorted                          69f9c273a0ff022c...
    "k=v" semicolon-joined, sorted                        18b73fd9060e06bb...
    json sort_keys + compact, ensure_ascii=False          8480e21be0843668...

Dropping ``sort_keys``, letting ``json.dumps`` use its default separators, or
passing ``ensure_ascii=False`` each looks like a tidy-up and silently re-keys
every variation in the product. That is what these vectors stand in the way of.

THE INPUT ABOVE CARRIES A NON-ASCII NAME ON PURPOSE, and the seventh row is why.
``ensure_ascii=False`` produces byte-identical output to the default for every
ASCII-only variation, so a table built on ``{"w": "2mm", "h": "1.6mm"}`` — which
is what this file pinned until Part 7 — cannot see it at all. A variation named
``width_µm`` or ``Ω_port`` is ordinary in an EM tool, and it is the only input
shape under which that one-line change is visible.

WHAT CANNOT BE PINNED HERE, stated so its absence is not read as an oversight:
the ``.encode("utf-8")`` argument. ``ensure_ascii`` (left at its default) keeps
the canonical string pure ASCII for EVERY input, so ``utf-8``, ``ascii``,
``latin-1`` and ``cp1252`` produce identical bytes and no input to
``_variation_hash`` can separate them. This file asserted the opposite until
Part 7 — ``test_the_encoding_is_utf_8_and_a_non_ascii_name_proves_it`` claimed a
non-ASCII name "proves" the encoding, and it did not, because ``json.dumps`` had
already escaped the name to ``\\u00b5`` before ``.encode`` ever saw it. The
replacement below asserts the real relationship: pin ``ensure_ascii``, and the
encoding follows from it.

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
    # THE NON-ASCII VECTOR, and the only one that pins ``ensure_ascii``. Note
    # what the canonical bytes are: ``µ`` as six literal ASCII characters,
    # not the two utf-8 bytes of ``µ``. That escaping IS ``ensure_ascii`` at its
    # default, and dropping it changes these bytes while leaving all three
    # vectors above untouched.
    (
        "a non-ASCII variable name",
        {"width_µm": "2", "h": "1.6mm"},
        b'{"h":"1.6mm","width_\\u00b5m":"2"}',
        "sha256:06f3009c529bdd65c76b3ca32f7e4d2ccc5cee315832e6a794ebf3f7874b8644",
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


def test_seven_near_miss_canonicalizations_give_seven_different_digests() -> None:
    """THE MEASUREMENT BEHIND THIS FILE, recomputed rather than quoted.

    The module docstring lists these; this asserts they really are all distinct,
    so the claim "byte-for-byte matters" is a fact the suite re-establishes on
    every run rather than a number someone wrote down once.

    Each variant is ONE line different from the real implementation. That is the
    point: none of them looks like a breaking change at a glance.

    THE INPUT MUST CARRY A NON-ASCII NAME or this test silently weakens to six:
    ``ensure_ascii=False`` is byte-identical to the default on ASCII-only input,
    so over ``{"w": "2mm", "h": "1.6mm"}`` the seventh variant collides with the
    first and the assertion below fails for the wrong reason. Asserted rather
    than commented, immediately after the loop.
    """
    values = {"width_µm": "2", "h": "1.6mm"}
    canonicalizations = (
        json.dumps(values, sort_keys=True, separators=(",", ":")),  # the real one
        json.dumps(values, sort_keys=True),  # default separators
        json.dumps(values, separators=(",", ":")),  # no sort_keys
        repr(sorted(values.items())),
        "\n".join(f"{key}={value}" for key, value in sorted(values.items())),
        ";".join(f"{key}={value}" for key, value in sorted(values.items())),
        json.dumps(  # ensure_ascii dropped
            values, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ),
    )
    digests = {
        hashlib.sha256(text.encode("utf-8")).hexdigest() for text in canonicalizations
    }
    assert len(digests) == len(canonicalizations)
    # The guard the docstring promises: the seventh variant is only distinct
    # BECAUSE the input carries a non-ASCII name. On an ASCII-only map it is the
    # first variant exactly, which is what made it invisible before Part 7.
    ascii_only = {"w": "2mm", "h": "1.6mm"}
    assert json.dumps(
        ascii_only, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ) == json.dumps(ascii_only, sort_keys=True, separators=(",", ":"))
    # And the first one is the one the product actually uses.
    assert _variation_hash(values) == DIGEST_PREFIX + hashlib.sha256(
        canonicalizations[0].encode("utf-8")
    ).hexdigest()


def test_the_encoding_argument_cannot_be_pinned_and_ensure_ascii_is_why() -> None:
    """WHAT THIS FILE CAN AND CANNOT HOLD, measured — replacing an assertion that
    named a property it did not test.

    The predecessor was ``test_the_encoding_is_utf_8_and_a_non_ascii_name_proves
    _it``, and it did not prove it. ``json.dumps`` escapes non-ASCII by default,
    so ``{"width_µm": "2"}`` canonicalises to the pure-ASCII
    ``{"width_\\u00b5m":"2"}`` — the name is already gone before ``.encode`` is
    reached, and utf-8, ascii, latin-1 and cp1252 return the same bytes for it.
    Swapping the encoding to any other single-byte codec left that test green.

    So the honest split, both halves asserted here:

      * ``ensure_ascii`` IS pinnable and IS pinned — by the fourth golden vector
        and by the seventh near-miss above. Dropping it changes the digest for a
        non-ASCII name and for nothing else.
      * The ENCODING ARGUMENT is not pinnable by any input, because there is no
        input for which the canonical string is not pure ASCII. That is a
        property of the canonicalization, not a gap in the suite, and it is why
        no test here claims to guard it.

    The two are not independent: pin ``ensure_ascii`` and the encoding stops
    mattering, which is the whole reason the first bullet is where the effort
    went.
    """
    values = {"width_µm": "2"}
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"))
    # ``ensure_ascii`` at its default is what makes this true, for EVERY input.
    assert canonical.isascii()
    assert "\\u00b5" in canonical
    assert "µ" not in canonical

    # THE PRODUCT'S OWN OUTPUT, not a recipe recomputed beside it. Every codec
    # reproduces what ``_variation_hash`` actually returned, which is the claim —
    # asserting it over a locally-built string would leave this test green if the
    # function stopped using this canonicalization at all.
    digest = _variation_hash(values)
    for codec in ("utf-8", "ascii", "latin-1", "cp1252"):
        assert (
            digest
            == DIGEST_PREFIX + hashlib.sha256(canonical.encode(codec)).hexdigest()
        ), f"{codec} disagrees, so the encoding argument IS observable after all"

    # A multi-byte codec IS distinguishable, which is the narrow sense in which
    # the encoding is constrained at all — and not the sense anyone would drift
    # into by accident.
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
