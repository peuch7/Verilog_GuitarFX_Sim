"""Reference model: hard-clipping distortion with a tone control.

Signal path: gain -> symmetric hard clip -> one-pole tone tilt -> output level.
Hard clipping is what makes this distortion rather than overdrive: the transfer
curve has a corner, so it generates strong odd harmonics immediately rather than
easing into them.

    drive  1..64   pre-clip gain; the clip threshold stays at 1.0
    tone   0..1    0 = dark (~800 Hz one-pole), 1 = open (~12 kHz)
    level  0..1    output attenuation, applied after clipping
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

from . import get

TONE_MIN_HZ = 800.0
TONE_MAX_HZ = 12000.0


def process(x: np.ndarray, params: dict, fs: int = 48000) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    drive = float(get(params, "drive", 4.0))
    tone = float(get(params, "tone", 0.5))
    level = float(get(params, "level", 0.5))

    y = np.clip(x * drive, -1.0, 1.0)
    y = tone_filter(y, tone, fs)
    return y * level


def tone_filter(y: np.ndarray, tone: float, fs: int) -> np.ndarray:
    """One-pole lowpass whose cutoff sweeps logarithmically with ``tone``."""
    tone = float(np.clip(tone, 0.0, 1.0))
    cutoff = TONE_MIN_HZ * (TONE_MAX_HZ / TONE_MIN_HZ) ** tone
    # Standard one-pole: y[n] = a*x[n] + (1-a)*y[n-1]
    a = 1.0 - np.exp(-2.0 * np.pi * cutoff / fs)
    return lfilter([a], [1.0, -(1.0 - a)], y)
