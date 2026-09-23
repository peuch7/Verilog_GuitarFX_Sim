"""Tests for the chorus effect.

The interesting ones are the fractional-delay tests. A chorus whose read pointer
snaps to whole samples still passes a casual listen and still correlates well
with the reference, but it steps audibly. test_fractional_delay_splits_an_impulse
fails immediately if the interpolation is dropped, which is why it is here.
"""

import numpy as np
import pytest

from wavsim import metrics, signals, stream
from wavsim.manifest import Manifest
from wavsim.pipeline import process_array, reference_array

EFFECT = "chorus"


@pytest.fixture(scope="module")
def manifest():
    return Manifest.load(EFFECT)


def test_silence_in_silence_out(manifest, backend):
    x = signals.silence(0.05)
    y, _ = process_array(manifest, x, backend=backend)
    assert np.max(np.abs(y)) == 0.0


def test_output_count_matches_input(manifest, backend):
    x = signals.sine(1000.0, 0.05)
    _, result = process_array(manifest, x, backend=backend)
    assert result.samples_out == result.samples_in


def test_dry_only_is_a_passthrough(manifest, backend):
    """mix = 0 must leave the signal alone, whatever the LFO is doing."""
    x = signals.sine(440.0, 0.05, amplitude=0.5)
    y, _ = process_array(manifest, x, {"mix": "0"}, backend=backend)
    assert metrics.compare(x, y).snr_db > 80.0


def test_static_delay_lands_at_the_right_place(manifest, backend):
    """depth = 0 turns it into a plain delay of base_ms."""
    x = signals.impulse(seconds=0.05, amplitude=0.9)
    y, _ = process_array(
        manifest, x,
        {"mix": "1.0", "depth": "0", "base_ms": "12.0"},   # 12 ms = 576 samples
        backend=backend,
    )
    index, _ = metrics.impulse_peak(y)
    assert index == 576


def test_fractional_delay_splits_an_impulse(manifest, backend):
    """The whole point of the effect: the read pointer moves sub-sample.

    base_ms = 12.1 ms is 580.8 samples, so an impulse must come back split
    across samples 580 and 581 in a 0.2/0.8 ratio. A design that truncated its
    address would put all of it on one sample.
    """
    x = signals.impulse(seconds=0.05, amplitude=0.9)
    y, _ = process_array(
        manifest, x,
        {"mix": "1.0", "depth": "0", "base_ms": "12.1"},
        backend=backend,
    )

    near, far = float(y[580]), float(y[581])
    assert near > 0.0 and far > 0.0, "impulse did not split across two samples"
    # The delay fraction is quantised to 12 bits, so 0.8 becomes 3276/4096.
    frac = 3276 / 4096
    assert near == pytest.approx(0.9 * (1.0 - frac), rel=2e-3)
    assert far == pytest.approx(0.9 * frac, rel=2e-3)
    # Nothing should land anywhere else.
    assert np.max(np.abs(np.delete(y, [580, 581]))) < 1e-6


def test_modulation_actually_modulates(manifest, backend):
    """depth > 0 must produce something different from a static delay."""
    x = signals.sine(1000.0, 0.5, amplitude=0.5)
    static, _ = process_array(manifest, x, {"mix": "1.0", "depth": "0"}, backend=backend)
    swept, _ = process_array(manifest, x, {"mix": "1.0", "depth": "3.0"}, backend=backend)
    assert metrics.compare(static, swept, align=False).snr_db < 20.0


@pytest.mark.parametrize(
    "overrides",
    [
        {"mix": "1.0"},
        {"mix": "0.5"},
        {"mix": "1.0", "rate": "3.0", "depth": "5.0"},
        {"mix": "0.5", "rate": "0.5", "depth": "1.0", "base_ms": "8.0"},
    ],
)
def test_matches_reference(manifest, backend, overrides):
    """Against the float model across the knob range.

    75 dB is the bar rather than 85: the LFO reads a 1024-point sine table and
    interpolates between entries, and that chord-versus-arc error is the
    dominant residual. Enlarging the table would buy a few more dB at the cost
    of BRAM, and it is not audible.
    """
    x = signals.sine(1000.0, 0.5, amplitude=0.5)
    rtl, _ = process_array(manifest, x, overrides, backend=backend)
    ref = reference_array(manifest, x, overrides)
    comparison = metrics.compare(ref, rtl)
    assert comparison.snr_db > 75.0, comparison.report()


def test_lfo_rate_does_not_drift(manifest, backend):
    """The LFO must still be in phase with the reference at the end of a clip.

    A rate error is not a constant offset: it accumulates, so the only way to
    see it is to compare late in a long clip. This test exists because a phase
    constant that was 60 ppm off once passed every short test while pulling the
    LFO a full sample out of step after a few seconds.
    """
    x = signals.sine(1000.0, 2.0, amplitude=0.5)
    overrides = {"mix": "1.0", "rate": "2.0", "depth": "4.0"}
    rtl, _ = process_array(manifest, x, overrides, backend=backend)
    ref = reference_array(manifest, x, overrides)

    quarter = len(x) // 4
    early = metrics.compare(ref[:quarter], rtl[:quarter], align=False).snr_db
    late = metrics.compare(ref[-quarter:], rtl[-quarter:], align=False).snr_db
    assert late > 70.0, f"LFO has drifted by the end of the clip: {late:.1f} dB"
    assert early - late < 12.0, (
        f"accuracy degrades over time ({early:.1f} dB -> {late:.1f} dB), "
        "which means a rate error rather than a rounding error"
    )


def test_full_scale_input_does_not_wrap(manifest, backend):
    """Checked by linearity: halving the input must halve the output."""
    loud = 0.999 * np.sign(signals.sine(200.0, 0.05))
    quiet = loud * 0.5
    overrides = {"mix": "0.5", "depth": "3.0"}

    y_loud, _ = process_array(manifest, loud, overrides, backend=backend)
    y_quiet, _ = process_array(manifest, quiet, overrides, backend=backend)

    assert np.max(np.abs(y_loud)) <= 1.0
    comparison = metrics.compare(2.0 * y_quiet, y_loud, align=False)
    assert comparison.snr_db > 70.0, comparison.report()


def test_runs_at_the_real_hardware_clock_ratio(manifest, backend):
    """Real time is not in question: the design uses 13 of 2083 clocks.

    The harness pulses sample_in_valid every 32 clocks to keep simulations
    short. Hardware gives 100 MHz / 48 kHz = 2083 clocks per sample, so this
    runs the same audio at the real ratio and requires the output to be
    identical - the simulation speedup must not be doing the design any
    favours.
    """
    x = signals.sine(440.0, 0.05, amplitude=0.5)
    fast, _ = process_array(manifest, x, {"mix": "0.5"}, backend=backend,
                            cycles_per_sample=32)
    real, _ = process_array(manifest, x, {"mix": "0.5"}, backend=backend,
                            cycles_per_sample=2083)
    assert np.array_equal(stream.float_to_samples(fast), stream.float_to_samples(real))


def test_minimum_cycles_per_sample(manifest, backend):
    """The sequencer needs 13 clocks, and has no back-pressure below that.

    Feeding samples faster than the sequencer runs makes it drop them, because
    sample_in_valid is only looked at in S_IDLE. That is harmless at 2083 clocks
    per sample, but it is a real constraint if the design is ever time-shared
    across channels or moved to a higher sample rate, so it is pinned here.
    """
    x = signals.sine(440.0, 0.02, amplitude=0.5)
    reference, _ = process_array(manifest, x, {"mix": "0.5"}, backend=backend,
                                 cycles_per_sample=32)
    expected = stream.float_to_samples(reference)

    at_limit, _ = process_array(manifest, x, {"mix": "0.5"}, backend=backend,
                                cycles_per_sample=13)
    assert np.array_equal(stream.float_to_samples(at_limit), expected), (
        "13 clocks per sample should be enough"
    )

    too_fast, _ = process_array(manifest, x, {"mix": "0.5"}, backend=backend,
                                cycles_per_sample=12)
    assert not np.array_equal(stream.float_to_samples(too_fast), expected), (
        "12 clocks per sample should drop samples; if this passes the sequencer "
        "got shorter and the documented budget needs updating"
    )


def test_generated_header_is_current(manifest):
    """The committed sine/constants header must match the manifest.

    The header carries the delay scaling derived from the manifest's units, so
    editing a knob's `factor` without regenerating leaves the RTL applying the
    old scaling. That is silent: it still runs, still sounds like a chorus, and
    is simply mistuned.
    """
    import subprocess
    import sys

    from wavsim.paths import EFFECTS_RTL, REPO_ROOT

    header = EFFECTS_RTL / "chorus" / "chorus_sine_table.svh"
    before = header.read_text()
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "gen_sine_table.py")],
        cwd=str(REPO_ROOT), capture_output=True, check=True,
    )
    after = header.read_text()
    if before != after:
        header.write_text(before)   # leave the tree as we found it
        pytest.fail(
            "chorus_sine_table.svh is stale against configs/effects/chorus.json. "
            "Run: python3 scripts/gen_sine_table.py"
        )


@pytest.mark.parametrize("base_ms", [4.0, 8.0, 12.0, 20.0])
def test_base_ms_is_really_milliseconds(manifest, backend, base_ms):
    """base_ms must mean milliseconds, whatever units the bus stores it in.

    This is the check that pins the manifest's declared unit to what the RTL
    actually does, rather than trusting the two to stay in step.
    """
    x = signals.impulse(seconds=0.1, amplitude=0.9)
    y, _ = process_array(
        manifest, x,
        {"mix": "1.0", "depth": "0", "base_ms": str(base_ms)},
        backend=backend,
    )
    index, _ = metrics.impulse_peak(y)
    expected = round(base_ms * 48)      # 48 samples per ms at 48 kHz
    assert abs(index - expected) <= 1, (
        f"base_ms={base_ms} ms should delay by ~{expected} samples, got {index}"
    )


def test_depth_is_really_milliseconds(manifest, backend):
    """depth must mean milliseconds too, measured as pitch deviation.

    A modulated delay detunes by d(delay)/dt, so the peak swing is
    2*pi*rate*depth. That makes the pitch swing a direct read-out of depth's
    unit - and a depth scaled ten times too large is exactly what "the chorus
    sounds out of tune" means.
    """
    scipy_signal = pytest.importorskip("scipy.signal")

    fs, f0 = 48000, 440.0
    rate, depth_ms = 1.0, 2.0
    x = signals.sine(f0, 3.0, amplitude=0.5)
    y, _ = process_array(
        manifest, x,
        {"mix": "1.0", "rate": str(rate), "depth": str(depth_ms), "base_ms": "12.0"},
        backend=backend,
    )

    phase = np.unwrap(np.angle(scipy_signal.hilbert(y)))
    inst = np.diff(phase) / (2 * np.pi) * fs
    cents = 1200 * np.log2(inst[fs // 2 : -fs // 2] / f0)

    expected = 1200 * np.log2(1 + 2 * np.pi * rate * depth_ms / 1000.0)
    assert float(np.abs(cents).max()) == pytest.approx(expected, rel=0.15), (
        f"pitch swing {np.abs(cents).max():.1f} cents, expected ~{expected:.1f}; "
        "depth is being scaled by the wrong unit"
    )


def test_gold_vector(manifest, backend, assert_gold):
    x = signals.pluck(82.41, seconds=0.25)
    y, _ = process_array(manifest, x, {"mix": "0.5", "rate": "1.5"}, backend=backend)
    assert_gold("chorus_pluck", stream.float_to_samples(y))
