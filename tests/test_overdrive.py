"""Tests for the overdrive effect.

These run the real RTL through the real harness, so they fail for design bugs and
for harness regressions alike. Start with the two below and add assertions that
describe what overdrive must do.
"""

import numpy as np
import pytest

from wavsim import signals
from wavsim.manifest import Manifest
from wavsim.pipeline import process_array

EFFECT = "overdrive"


@pytest.fixture(scope="module")
def manifest():
    return Manifest.load(EFFECT)


def test_silence_in_silence_out(manifest, backend):
    """Nothing in, nothing out. Catches uninitialised state and stray offsets."""
    x = signals.silence(0.05)
    y, _ = process_array(manifest, x, backend=backend)
    assert np.max(np.abs(y)) == 0.0


def test_output_count_matches_input(manifest, backend):
    """One sample_out_valid per sample_in_valid, which the harness counts."""
    x = signals.sine(1000.0, 0.05)
    y, result = process_array(manifest, x, backend=backend)
    assert result.samples_out == result.samples_in


@pytest.mark.skip(reason="TODO: implement overdrive.sv, then describe its behaviour here")
def test_overdrive_behaviour(manifest, backend):
    raise NotImplementedError
