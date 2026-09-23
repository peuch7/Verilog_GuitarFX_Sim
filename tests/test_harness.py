"""Tests for the harness itself, rather than for any one effect.

These enforce the invariants documented in docs/architecture.md. Each one exists
because breaking it would fail quietly somewhere else — a gold vector that stops
being portable, an output stream shifted by one sample, a knob that means two
different things depending on how it was typed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

from wavsim import SAMPLE_MAX, SAMPLE_MIN, resample, signals, stream
from wavsim.manifest import Manifest, ManifestError, parse_param_string
from wavsim.paths import EFFECT_CONFIGS, REPO_ROOT


# --------------------------------------------------------------------------
# invariant 3: the resampler stays dependency-free


def test_resampler_does_not_use_scipy():
    """The wav -> stream front end must be reproducible across environments.

    scipy is fine everywhere else, but resample.py sits upstream of every run on
    real audio, so its output has to be identical on the host and in the
    container regardless of which scipy each has.
    """
    tree = ast.parse((REPO_ROOT / "tools" / "wavsim" / "resample.py").read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "scipy" not in imported, (
        "resample.py must not import scipy; see docs/architecture.md"
    )


def test_resampler_is_accurate():
    """A 1 kHz sine through 44.1 -> 48 kHz must stay clean and keep its length."""
    fs_in, fs_out = 44100, 48000
    t = np.arange(fs_in) / fs_in
    x = 0.5 * np.sin(2.0 * np.pi * 1000.0 * t)
    y = resample.resample(x, fs_in, fs_out)

    assert y.size == int(x.size * fs_out / fs_in)

    spectrum = np.abs(np.fft.rfft(y * np.hanning(y.size)))
    peak_bin = int(np.argmax(spectrum))
    assert abs(peak_bin * fs_out / y.size - 1000.0) < 2.0

    # Everything outside the fundamental must be far down.
    spectrum /= spectrum.max()
    spectrum[max(peak_bin - 5, 0) : peak_bin + 5] = 0.0
    assert 20.0 * np.log10(spectrum.max()) < -90.0


def test_resampler_is_identity_at_the_same_rate():
    x = signals.sine(440.0, 0.01)
    assert np.array_equal(resample.resample(x, 48000, 48000), x)


# --------------------------------------------------------------------------
# invariant 5: the int24 round trip is exact


def test_sample_round_trip_is_exact():
    """float64 holds a 24-bit integer scaled by 2**-23 losslessly."""
    values = np.arange(SAMPLE_MIN, SAMPLE_MAX, 997, dtype=np.int32)
    assert np.array_equal(
        stream.float_to_samples(stream.samples_to_float(values)), values
    )


def test_samples_are_clipped_not_wrapped():
    """Out-of-range floats must saturate; wrapping would invert loud samples."""
    x = np.array([-2.0, -1.0, 0.0, 0.5, 1.0, 2.0])
    out = stream.float_to_samples(x)
    assert out.min() == SAMPLE_MIN
    assert out.max() == SAMPLE_MAX


def test_stream_write_rejects_out_of_range(tmp_path):
    bad = np.array([SAMPLE_MAX + 1], dtype=np.int32)
    with pytest.raises(ValueError):
        stream.write(tmp_path / "bad.pcm24", bad)


def test_stream_file_round_trip(tmp_path):
    samples = stream.float_to_samples(signals.noise(0.01))
    path = tmp_path / "s.pcm24"
    stream.write(path, samples, stream.StreamMeta(source="unit test"))
    assert np.array_equal(stream.read(path), samples)
    assert stream.StreamMeta.load(path).n_samples == samples.size

    # The text form the Icarus backend uses must carry the same values.
    text = tmp_path / "s.pcm24.txt"
    stream.write_text(text, samples)
    assert np.array_equal(stream.read_text(text), samples)


def test_empty_text_stream_reads_as_empty(tmp_path):
    """A simulator that produced nothing must not crash the back end."""
    path = tmp_path / "empty.pcm24.txt"
    path.write_text("")
    assert stream.read_text(path).size == 0


# --------------------------------------------------------------------------
# invariant 2: bits and natural units are exact inverses


ALL_EFFECTS = Manifest.list_effects()


@pytest.mark.parametrize("effect", ALL_EFFECTS)
def test_bits_and_natural_units_are_inverses(effect):
    """natural(resolve(x)) must return the values that produced those bits."""
    manifest = Manifest.load(effect)
    natural = manifest.natural()
    # Feeding the natural values back in as floats must reproduce the same bus.
    round_tripped = manifest.resolve({k: float(v) for k, v in natural.items()})
    assert round_tripped == manifest.resolve()


@pytest.mark.parametrize("effect", ALL_EFFECTS)
def test_manifest_defaults_are_in_range(effect):
    """A manifest whose own default is out of range would fail on first use."""
    Manifest.load(effect).resolve()


@pytest.mark.parametrize("effect", ALL_EFFECTS)
def test_manifest_matches_its_wrapper(effect):
    """Every named slot must actually be wired up in the wrapper."""
    manifest = Manifest.load(effect)
    wrapper = next(s for s in manifest.sources if s.name.endswith("_top.sv"))
    text = wrapper.read_text()
    for param in manifest.params:
        assert f"`PARAM({param.index})" in text, (
            f"{effect}: slot {param.index} ({param.name}) is declared in the "
            f"manifest but never sliced in {wrapper.name}"
        )


def test_decimal_is_natural_and_integer_is_bits():
    """The one parameter rule, pinned."""
    manifest = Manifest.load("delay")
    assert manifest.resolve({"mix": "0.5"})[2] == 32768   # natural units
    assert manifest.resolve({"mix": "32768"})[2] == 32768  # raw bits
    assert manifest.resolve({"mix": "50%"})[2] == 32768    # percent


def test_unknown_parameter_is_rejected():
    with pytest.raises(ManifestError):
        Manifest.load("delay").resolve({"not_a_knob": 1})


def test_out_of_range_parameter_is_rejected():
    with pytest.raises(ManifestError):
        Manifest.load("delay").resolve({"delay_samples": 60000})  # max is 48000


def test_param_string_parsing():
    assert parse_param_string("mix=0.5, feedback=0.4") == {"mix": "0.5", "feedback": "0.4"}
    with pytest.raises(ManifestError):
        parse_param_string("mix")


# --------------------------------------------------------------------------
# invariant 6: matplotlib is never imported at startup


def test_plots_are_not_imported_eagerly():
    """matplotlib is a dev extra; importing the CLI must not need it."""
    for module in ("__init__", "cli", "pipeline", "backends"):
        source = (REPO_ROOT / "tools" / "wavsim" / f"{module}.py").read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)) and node.col_offset == 0:
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                assert not any(n.startswith("matplotlib") for n in names), (
                    f"{module}.py imports matplotlib at module level"
                )


# --------------------------------------------------------------------------
# wav handling


@pytest.mark.parametrize("bits", [16, 24, 32])
def test_wav_round_trip(tmp_path, bits):
    from wavsim import wavio

    x = signals.sine(1000.0, 0.02, amplitude=0.5)
    path = tmp_path / f"t{bits}.wav"
    wavio.write_wav(path, x, 48000, bits=bits)
    y, rate = wavio.read_wav(path)

    assert rate == 48000
    assert y.size == x.size
    assert np.max(np.abs(x - y)) < 2.0 ** -(bits - 2)


def test_stereo_is_downmixed(tmp_path):
    """A stereo wav must collapse to one channel; the pedal path is mono."""
    from wavsim import wavio
    from wavsim.pipeline import load_input

    import wave

    left = signals.sine(1000.0, 0.02, amplitude=0.5)
    right = -left  # cancels exactly on downmix
    interleaved = np.empty(left.size * 2)
    interleaved[0::2] = left
    interleaved[1::2] = right

    path = tmp_path / "stereo.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(3)
        w.setframerate(48000)
        w.writeframes(wavio._encode_int24(wavio._quantize(interleaved, 23)))

    mono = load_input(path)
    assert mono.size == left.size
    assert np.max(np.abs(mono)) < 1e-6


# --------------------------------------------------------------------------
# effect registry


def test_every_manifest_has_a_reference_model():
    from wavsim import refmodels

    for effect in ALL_EFFECTS:
        manifest = Manifest.load(effect)
        assert manifest.reference_model, f"{effect} has no reference_model"
        model = refmodels.load(manifest.reference_model)
        assert callable(model)


def test_every_manifest_file_is_loadable():
    """Catches a hand-edited manifest with a typo before anyone runs a sim."""
    for path in EFFECT_CONFIGS.glob("*.json"):
        Manifest.load(path)
