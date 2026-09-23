"""Reference model: chorus — an LFO-modulated short delay mixed with the dry signal.

The delay is a few milliseconds and swept by a low-frequency sine, so the wet
copy is continuously slightly sharp or flat against the dry one. That detuning
is the whole effect, which means the fractional part of the delay matters: a
chorus that rounds its read pointer to whole samples sounds gritty and steps
audibly. Whoever implements this in RTL needs interpolation between adjacent
buffer entries, not a truncated address.

    rate     0.1..8 Hz    LFO frequency
    depth    0..10 ms     peak sweep either side of base_ms
    mix      0..1         dry/wet balance
    base_ms  1..30 ms     centre delay (defaults to 12 ms)

There is no feedback path here, so the read is a pure function of the input and
the model is vectorised rather than looped.
"""

from __future__ import annotations

import numpy as np

from . import get


def process(x: np.ndarray, params: dict, fs: int = 48000) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    rate = float(get(params, "rate", 1.0))
    depth_ms = float(get(params, "depth", 3.0))
    mix = float(get(params, "mix", 0.5))
    base_ms = float(params.get("base_ms", 12.0))

    n = np.arange(x.size, dtype=np.float64)
    lfo = np.sin(2.0 * np.pi * rate * n / fs)
    delay = (base_ms + depth_ms * lfo) * fs / 1000.0
    delay = np.clip(delay, 0.0, None)

    wet = _read_fractional(x, n - delay)
    return x * (1.0 - mix) + wet * mix


def _read_fractional(x: np.ndarray, pos: np.ndarray) -> np.ndarray:
    """Linear interpolation at fractional positions, zero outside the signal."""
    base = np.floor(pos)
    frac = pos - base
    i0 = base.astype(np.int64)
    i1 = i0 + 1

    valid0 = (i0 >= 0) & (i0 < x.size)
    valid1 = (i1 >= 0) & (i1 < x.size)
    s0 = np.where(valid0, x[np.clip(i0, 0, x.size - 1)], 0.0)
    s1 = np.where(valid1, x[np.clip(i1, 0, x.size - 1)], 0.0)
    return s0 * (1.0 - frac) + s1 * frac
