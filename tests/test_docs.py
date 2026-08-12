"""Phase 7: the numbers quoted in README.md are real.

Every figure in the README was measured once and then written down, which is
exactly the arrangement that rots. These tests re-measure them. If a fixture is
replaced or the range table is amended, the documentation fails alongside the
code instead of quietly becoming fiction.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from objstego import hide, payload_capacity
from objstego.obj_io import parse_obj
from objstego.pvd import pair_usable
from objstego.ranges import range_table

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).parent / "data"
README = (ROOT / "README.md").read_text()


def _usable_pairs(text: str, low: int = 3) -> tuple[int, int]:
    table = range_table(low)
    lows = [value % table.mod for value in parse_obj(text, 6).coordinates()]
    total = usable = 0
    for index in range(0, len(lows) - 1, 2):
        a, b = lows[index], lows[index + 1]
        total += 1
        if pair_usable(a, b, table.find(abs(b - a))[1], table.mod):
            usable += 1
    return usable, total


@pytest.mark.parametrize(
    "mesh,vertices,usable,total,distinct,capacity",
    [
        ("cube.obj", 8, 0, 12, 1, 0),
        ("suzanne.obj", 507, 490, 760, 16, 403),
        ("car.obj", 711, 747, 1066, 299, 630),
    ],
)
def test_capacity_table(mesh, vertices, usable, total, distinct, capacity):
    """The table printed in README.md and tests/data/README.md."""
    text = (DATA / mesh).read_text()
    document = parse_obj(text, 6)

    assert document.vertex_count == vertices
    assert _usable_pairs(text) == (usable, total)
    assert len({value % 1000 for value in document.coordinates()}) == distinct
    assert payload_capacity(text) == capacity


def test_the_worked_example_produces_the_numbers_it_claims():
    """README "A real run": 14 bytes, 21 pairs used, 9 skipped."""
    cover = (DATA / "car.obj").read_text()

    _, result = hide(cover, b"attack at dawn")

    assert result.complete
    assert result.pairs_used == 21
    assert result.pairs_skipped == 9
    assert "hid 14 of 14 bytes in 21 pairs (9 skipped)" in README


def test_the_non_vertex_line_count_is_right():
    """README claims 1,469 non-`v` lines survive byte-identical in car.obj."""
    lines = (DATA / "car.obj").read_text().split("\n")[:-1]
    non_vertex = sum(1 for line in lines if not line.startswith("v "))

    assert non_vertex == 1469
    assert "1,469 of its non-`v` lines" in README


def test_the_range_table_in_the_readme_matches_the_code():
    """The bits row: 3, 3, 4, 5, 6, 7, 8, 8."""
    table = range_table(3)
    widths = [table.bits_for(lower) for lower, _ in table.ranges]

    assert widths == [3, 3, 4, 5, 6, 7, 8, 8]
    assert "| Bits | 3 | 3 | 4 | 5 | 6 | 7 | 8 | 8 |" in README


def test_the_readme_capacity_table_rows_are_present():
    for mesh, capacity in (("cube.obj", "0 bytes"), ("suzanne.obj", "403 bytes"),
                           ("car.obj", "630 bytes")):
        assert f"`{mesh}`" in README
        assert capacity in README


def test_the_declared_python_floor_matches_pyproject():
    pyproject = (ROOT / "pyproject.toml").read_text()
    declared = re.search(r'requires-python = ">=([\d.]+)"', pyproject)

    assert declared is not None
    assert f"Python {declared.group(1)} or newer" in README


def test_the_readme_documents_every_cli_option():
    from objstego.cli import USAGE

    for flag in ("--hide", "--extract", "-m", "-c", "-s", "-o", "-P", "-L"):
        assert flag in USAGE
        assert flag in README
