"""#826 — interface-contract v3 derivation (the SSOT AST walk).

Locks the deterministic derivation of the callable/arity/return-shape contract a job
oracle demands: the two supported call shapes (``from m import f`` then ``f(...)`` and
``import m`` then ``m.f(...)``), the arity fields (positional / keywords / *args / **kw),
the merge across multiple call sites, the asserted return shapes (the B4n2 string-eq
signal plus isinstance/len/subscript/attr/compare), the coder-facing render lines, and
the fail-soft/conservative negatives (unparseable, no-first-party, relative, stdlib).
"""

from __future__ import annotations

from shared.fleet import interface_contract as ic


def _c(code: str) -> ic.InterfaceContract:
    return ic.derive_interface_contract(code)


# ---------------------------------------------------------------------------
# Callable derivation — the two supported shapes + aliases + arity
# ---------------------------------------------------------------------------


def test_from_import_call_arity():
    contract = _c(
        "from flashcards import check_answer\n\n"
        "def test_x():\n    assert check_answer('cat', 'cat') == 'correct'\n"
    )
    assert len(contract.calls) == 1
    call = contract.calls[0]
    assert call.module == "flashcards" and call.name == "check_answer"
    assert call.positional == 2 and call.keywords == () and not call.starargs


def test_import_module_attribute_call():
    contract = _c(
        "import inventory\n\n"
        "def test_x():\n    inventory.add_item('widget', 5)\n"
    )
    assert contract.calls == (
        ic.CallSig("inventory", "add_item", 2, (), False, False),
    )


def test_aliases_from_and_module():
    from_alias = _c(
        "from m import compute as c\n\ndef test_x():\n    assert c(1) == 2\n"
    )
    assert from_alias.calls[0].module == "m" and from_alias.calls[0].name == "compute"
    mod_alias = _c(
        "import store as s\n\ndef test_x():\n    s.save(1, 2)\n"
    )
    assert mod_alias.calls[0].module == "store" and mod_alias.calls[0].name == "save"
    assert mod_alias.calls[0].positional == 2


def test_keywords_and_star_flags():
    contract = _c(
        "from greet import hello\n\n"
        "def test_x():\n    hello('bob', greeting='hi', *extra, **opts)\n"
    )
    call = contract.calls[0]
    assert call.positional == 1
    assert call.keywords == ("greeting",)
    assert call.starargs and call.starkwargs


# ---------------------------------------------------------------------------
# probe_signatures — the per-module arity contract + merge
# ---------------------------------------------------------------------------


def test_probe_signatures_shape():
    sigs = _c(
        "from flashcards import check_answer\n\n"
        "def test_x():\n    assert check_answer('a', 'b') == 'ok'\n"
    ).probe_signatures()
    assert sigs == {"flashcards": [
        {"name": "check_answer", "min_positional": 2, "max_positional": 2,
         "keywords": [], "starargs": False, "starkwargs": False},
    ]}


def test_probe_signatures_merges_call_sites():
    # f(1) and f(1, 2) → min 1 / max 2; the keyword unions; *args ORs in.
    contract = _c(
        "from m import f\n\n"
        "def test_a():\n    f(1)\n"
        "def test_b():\n    f(1, 2, mode=3)\n"
        "def test_c():\n    f(*xs)\n"
    )
    spec = contract.probe_signatures()["m"][0]
    assert spec["min_positional"] == 0 and spec["max_positional"] == 2
    assert spec["keywords"] == ["mode"]
    assert spec["starargs"] is True


# ---------------------------------------------------------------------------
# Return shapes — the B4n2 string-eq signal + the shape variants
# ---------------------------------------------------------------------------


def test_string_return_literal_only_strings():
    # str-eq is captured for the invented-return check; num-eq is NOT a string literal.
    contract = _c(
        "from q import check, score\n\n"
        "def test_x():\n"
        "    assert check('a') == 'correct'\n"
        "    assert score('a') == 42\n"
    )
    assert contract.string_return_literals() == [("check", "correct")]


def test_return_shape_variants_recorded():
    contract = _c(
        "from m import f, g, h, k\n\n"
        "def test_x():\n"
        "    assert isinstance(f(), dict)\n"
        "    assert len(g()) == 3\n"
        "    assert h()['key'] == 1\n"
        "    assert k().name == 'z'\n"
    )
    kinds = {(r.name, r.kind) for r in contract.returns}
    assert ("f", "isinstance") in kinds
    assert ("g", "len") in kinds
    assert ("h", "subscript") in kinds
    assert ("k", "attr") in kinds


def test_string_return_dedup():
    contract = _c(
        "from m import f\n\n"
        "def test_a():\n    assert f(1) == 'x'\n"
        "def test_b():\n    assert f(2) == 'x'\n"
    )
    assert contract.string_return_literals() == [("f", "x")]


# ---------------------------------------------------------------------------
# render_lines — the coder-facing signature surface (rec-1 v3)
# ---------------------------------------------------------------------------


def test_render_lines_shapes():
    lines = _c(
        "from m import check_answer, total, greet\n\n"
        "def test_x():\n"
        "    check_answer('a', 'b')\n"
        "    total()\n"
        "    greet('bob', greeting='hi')\n"
    ).render_lines()
    assert "check_answer(2 positional args)" in lines
    assert "total()" in lines
    assert "greet(1 positional arg, keyword: greeting)" in lines


# ---------------------------------------------------------------------------
# Conservative negatives + fail-soft
# ---------------------------------------------------------------------------


def test_unparseable_is_empty():
    assert _c("def broken( :::").calls == ()
    assert _c("").calls == ()


def test_no_first_party_is_empty():
    # A test that calls only stdlib / builtins → no contract callables.
    contract = _c(
        "import os\n\ndef test_x():\n    assert os.path.join('a', 'b')\n    assert len([]) == 0\n"
    )
    assert contract.calls == ()
    assert contract.callable_names() == set()


def test_relative_import_not_a_contract_callable():
    contract = _c(
        "from .helper import h\n\ndef test_x():\n    assert h(1) == 2\n"
    )
    assert contract.calls == ()


def test_stdlib_call_not_recorded():
    # `json.dumps(...)` is stdlib → never a first-party contract callable.
    contract = _c(
        "import json\nfrom m import f\n\n"
        "def test_x():\n    json.dumps(f(1))\n"
    )
    names = {c.name for c in contract.calls}
    assert names == {"f"} and "dumps" not in names


def test_custom_first_party_predicate():
    # A caller can narrow the first-party set; here everything is treated as stdlib.
    contract = ic.derive_interface_contract(
        "from m import f\n\ndef test_x():\n    f(1)\n",
        is_first_party=lambda top: False,
    )
    assert contract.calls == ()
