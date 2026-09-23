"""Reference model: Schroeder reverb — four parallel combs into two allpass stages.

The combs build up echo density, and the allpass sections smear the result so it
stops sounding like discrete repeats. The comb lengths are mutually prime (in
samples, at 48 kHz) on purpose: common factors would make repeats line up and
ring at an audible pitch instead of blurring.

This is the most memory-hungry effect in the set. The four combs plus two allpass
lines need roughly 9000 samples of storage at 24 bits, about 27 kB, which is
worth checking against the BRAM budget before anyone starts writing RTL.

    decay    0..1   feedback in the comb sections; higher = longer tail
    damping  0..1   lowpass inside the comb feedback, so highs decay first
    mix      0..1   dry/wet balance
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

from . import get

# Comb and allpass lengths in samples at 48 kHz, scaled from Schroeder's originals.
COMB_LENGTHS = (1687, 1801, 2113, 2311)
ALLPASS_LENGTHS = (241, 83)
ALLPASS_GAIN = 0.5


def process(x: np.ndarray, params: dict, fs: int = 48000) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    decay = float(get(params, "decay", 0.7))
    damping = float(get(params, "damping", 0.3))
    mix = float(get(params, "mix", 0.3))

    # Keep the combs stable no matter what the caller asks for.
    g = float(np.clip(decay, 0.0, 0.98))

    scale = fs / 48000.0
    wet = np.zeros_like(x)
    for length in COMB_LENGTHS:
        wet += _comb(x, max(int(round(length * scale)), 1), g, damping)
    wet /= len(COMB_LENGTHS)

    for length in ALLPASS_LENGTHS:
        wet = _allpass(wet, max(int(round(length * scale)), 1), ALLPASS_GAIN)

    return x * (1.0 - mix) + wet * mix


def _comb(x: np.ndarray, length: int, g: float, damping: float) -> np.ndarray:
    """Feedback comb with a one-pole lowpass in the loop (Moorer's variant)."""
    d = float(np.clip(damping, 0.0, 0.99))
    if d <= 0.0:
        # y[n] = x[n] + g*y[n-length]
        a = np.zeros(length + 1)
        a[0] = 1.0
        a[length] = -g
        return lfilter([1.0], a, x)

    # With damping the loop is y[n] = x[n] + g*((1-d)*y[n-L] + d*y[n-L-1]),
    # which is still a plain IIR and stays in lfilter's hands.
    a = np.zeros(length + 2)
    a[0] = 1.0
    a[length] = -g * (1.0 - d)
    a[length + 1] = -g * d
    return lfilter([1.0], a, x)


def _allpass(x: np.ndarray, length: int, g: float) -> np.ndarray:
    """Schroeder allpass: flat magnitude, dispersive phase."""
    b = np.zeros(length + 1)
    b[0] = -g
    b[length] = 1.0
    a = np.zeros(length + 1)
    a[0] = 1.0
    a[length] = -g
    return lfilter(b, a, x)
