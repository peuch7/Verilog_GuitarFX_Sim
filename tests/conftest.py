"""Shared pytest fixtures.

Tests run the real RTL through the real harness rather than mocking it, so a
failure means either a design bug or a harness regression. That is deliberate:
those are the two things worth catching before someone books time on the board.

    pytest                         # verilator (or whatever is installed)
    pytest --backend icarus        # the fallback simulator
    pytest --update-gold           # rewrite the stored regression vectors
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from wavsim import stream
from wavsim.backends import get_backend
from wavsim.manifest import Manifest
from wavsim.paths import GOLD_DIR


def pytest_addoption(parser):
    parser.addoption(
        "--backend",
        action="store",
        default="auto",
        choices=["auto", "verilator", "icarus"],
        help="simulator to run the tests against",
    )
    parser.addoption(
        "--update-gold",
        action="store_true",
        default=False,
        help="rewrite the stored gold vectors instead of comparing against them",
    )


@pytest.fixture(scope="session")
def backend(request) -> str:
    name = request.config.getoption("--backend")
    try:
        sim = get_backend(name, Manifest.load("delay"))
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"no usable simulator: {exc}")
    if not sim.available():
        pytest.skip(f"{name} is not installed; see `make doctor`")
    return name


@pytest.fixture(scope="session")
def update_gold(request) -> bool:
    return bool(request.config.getoption("--update-gold"))


@pytest.fixture
def assert_gold(update_gold):
    """Compare a run against its committed vector, or rewrite it on request.

    This is what catches "I changed my module and did not mean to change the
    sound". It stores 24-bit integers, so it is exact and a one-LSB drift fails.
    """

    def _assert(name: str, samples: np.ndarray) -> None:
        GOLD_DIR.mkdir(parents=True, exist_ok=True)
        path = GOLD_DIR / f"{name}.pcm24"
        ints = np.asarray(samples, dtype=stream.DTYPE)

        if update_gold or not path.exists():
            stream.write(path, ints, stream.StreamMeta(source=f"gold vector: {name}"))
            if not update_gold:
                pytest.skip(f"created missing gold vector {path.name}; rerun to check it")
            return

        expected = stream.read(path)
        if ints.size != expected.size:
            pytest.fail(
                f"{name}: produced {ints.size} samples, gold has {expected.size}"
            )
        if not np.array_equal(ints, expected):
            diff = np.nonzero(ints != expected)[0]
            worst = int(np.max(np.abs(ints.astype(np.int64) - expected.astype(np.int64))))
            pytest.fail(
                f"{name}: {diff.size} of {ints.size} samples differ from the gold vector "
                f"(first at {diff[0]}, worst {worst} LSB). "
                f"If the change was intended, rerun with --update-gold."
            )

    return _assert
