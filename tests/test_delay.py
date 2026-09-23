"""Tests for the delay effect.

These describe what a delay must do, then check delay.sv against it. Where the
RTL and the reference model currently disagree, the test says so explicitly
rather than being loosened until it passes — see test_feedback_path_known_gap.
"""

import numpy as np
import pytest

from wavsim import metrics, signals, stream
from wavsim.manifest import Manifest
from wavsim.pipeline import process_array, reference_array

EFFECT = "delay"


@pytest.fixture(scope="module")
def manifest():
    return Manifest.load(EFFECT)


def test_silence_in_silence_out(manifest, backend):
    """Catches uninitialised buffers and stray DC offsets."""
    x = signals.silence(0.05)
    y, _ = process_array(manifest, x, {"delay_samples": 500, "feedback": 0.5, "mix": 0.5},
                         backend=backend)
    assert np.max(np.abs(y)) == 0.0


def test_output_count_matches_input(manifest, backend):
    """One sample_out_valid per sample_in_valid."""
    x = signals.sine(1000.0, 0.05)
    _, result = process_array(manifest, x, backend=backend)
    assert result.samples_out == result.samples_in


@pytest.mark.parametrize("delay_samples", [1, 500, 4800])
def test_impulse_lands_at_the_requested_delay(manifest, backend, delay_samples):
    """The defining property: a wet-only impulse comes back exactly N samples later."""
    x = signals.impulse(seconds=(delay_samples + 2000) / 48000.0, amplitude=0.9)
    y, _ = process_array(
        manifest, x,
        {"delay_samples": delay_samples, "feedback": 0.0, "mix": 1.0},
        backend=backend,
    )
    index, value = metrics.impulse_peak(y)
    assert index == delay_samples
    # Full scale in, near full scale out: the only loss is the 65535/65536 mix scaling.
    assert value == pytest.approx(0.9, rel=1e-3)


def test_dry_only_is_a_passthrough(manifest, backend):
    """mix = 0 must leave the signal alone, whatever the delay line is doing."""
    x = signals.sine(440.0, 0.05, amplitude=0.5)
    y, _ = process_array(
        manifest, x,
        {"delay_samples": 1000, "feedback": 0.9, "mix": 0.0},
        backend=backend,
    )
    comparison = metrics.compare(x, y)
    assert comparison.snr_db > 80.0


def test_feedback_produces_decaying_repeats(manifest, backend):
    """Each repeat must be quieter than the last, or the loop is unstable."""
    delay_samples = 500
    x = signals.impulse(seconds=0.1, amplitude=0.9)
    y, _ = process_array(
        manifest, x,
        {"delay_samples": delay_samples, "feedback": 0.5, "mix": 1.0},
        backend=backend,
    )
    peaks = [
        float(np.max(np.abs(y[k * delay_samples : (k + 1) * delay_samples])))
        for k in range(1, 6)
    ]
    assert all(peaks[i + 1] < peaks[i] for i in range(len(peaks) - 1)), peaks
    assert peaks[0] > 0.0


def test_full_scale_input_does_not_wrap(manifest, backend):
    """Overflow is checked by linearity, not by looking for big jumps.

    A delay is a linear filter, so halving the input must halve the output. An
    accumulator that wraps breaks that badly, and unlike a jump threshold this
    works for any waveform - a square wave has legitimate full-scale jumps of
    its own.
    """
    overrides = {"delay_samples": 240, "feedback": 0.9, "mix": 0.5}
    loud = 0.999 * np.sign(signals.sine(200.0, 0.05))
    quiet = loud * 0.5

    y_loud, _ = process_array(manifest, loud, overrides, backend=backend)
    y_quiet, _ = process_array(manifest, quiet, overrides, backend=backend)

    assert np.max(np.abs(y_loud)) <= 1.0
    comparison = metrics.compare(2.0 * y_quiet, y_loud, align=False)
    assert comparison.snr_db > 70.0, (
        "output is not linear in the input, which means something overflowed\n"
        + comparison.report()
    )


def test_matches_reference_without_feedback(manifest, backend):
    """With feedback off, only fixed-point rounding should separate RTL and model."""
    overrides = {"delay_samples": 2400, "feedback": 0.0, "mix": 0.5}
    x = signals.sweep(20.0, 18000.0, 0.5)
    rtl, _ = process_array(manifest, x, overrides, backend=backend)
    ref = reference_array(manifest, x, overrides)
    comparison = metrics.compare(ref, rtl)
    assert comparison.snr_db > 80.0, comparison.report()


def test_feedback_path_known_gap(manifest, backend):
    """delay.sv's feedback write is one sample behind the reference model.

    delay.sv:74 stores ``sample_in*(1-feedback) + old_sample*feedback``, but
    ``old_sample`` is the buffer read registered on the *previous* valid sample,
    not the one being read on this one. So the recirculated signal is one sample
    period stale.

    This test pins the current behaviour instead of hiding it: with feedback on,
    the RTL and the model diverge well below the ~90 dB that rounding alone would
    give. When delay.sv is changed to feed back the current read, this test will
    fail, and that is the signal to delete it and tighten
    test_matches_reference_without_feedback to cover feedback too.
    """
    overrides = {"delay_samples": 2400, "feedback": 0.5, "mix": 0.5}
    x = signals.sweep(20.0, 18000.0, 0.5)
    rtl, _ = process_array(manifest, x, overrides, backend=backend)
    ref = reference_array(manifest, x, overrides)
    comparison = metrics.compare(ref, rtl)
    assert comparison.snr_db < 80.0, (
        "delay.sv now matches the reference with feedback engaged. "
        "Remove this test and extend test_matches_reference_without_feedback.\n"
        + comparison.report()
    )


def test_gold_vector(manifest, backend, assert_gold):
    """Regression guard: flags any change to what the module actually outputs."""
    x = signals.pluck(82.41, seconds=0.25)
    y, _ = process_array(
        manifest, x,
        {"delay_samples": 2400, "feedback": 0.4, "mix": 0.5},
        backend=backend,
    )
    assert_gold("delay_pluck", stream.float_to_samples(y))
