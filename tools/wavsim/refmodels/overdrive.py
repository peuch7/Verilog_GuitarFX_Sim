"""Reference model: soft-clipping overdrive.

Same shape as distortion but with a smooth transfer curve, so the harmonics come
in gradually with playing level instead of switching on at a corner. The curve is
tanh normalised so that a full-scale input stays full scale at any drive:

    y = tanh(drive * x) / tanh(drive)

An asymmetry term biases the curve slightly, which is what gives real tube-style
overdrive its even harmonics.

    drive      1..32   pre-clip gain into the tanh
    tone       0..1    same one-pole tilt as distortion
    level      0..1    output attenuation
    asymmetry  0..1    0 = symmetric, higher adds even harmonics
"""

from __future__ import annotations

import numpy as np

from . import get
from .distortion import tone_filter


def process(x: np.ndarray, params: dict, fs: int = 48000) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    drive = float(get(params, "drive", 4.0))
    tone = float(get(params, "tone", 0.5))
    level = float(get(params, "level", 0.5))
    asymmetry = float(get(params, "asymmetry", 0.0))

    drive = max(drive, 1e-6)
    bias = 0.3 * asymmetry
    y = np.tanh(drive * x + bias) - np.tanh(bias)
    y /= np.tanh(drive)

    y = tone_filter(y, tone, fs)
    return y * level
