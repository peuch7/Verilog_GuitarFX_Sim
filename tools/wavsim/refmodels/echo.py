"""Reference model: echo — a fixed number of discrete decaying repeats.

The difference from `delay` is architectural, and it matters for whoever builds
it in RTL. A delay recirculates its output, so it needs one buffer and a
feedback multiplier but produces infinitely many (decaying) repeats. An echo
here is feed-forward: a fixed set of taps read from one buffer at multiples of
the same spacing, each scaled by ``decay**k``. No feedback path means no
stability question and no risk of a runaway level, at the cost of a hard limit
on the repeat count.

    delay_samples  0..48000   spacing between repeats
    decay          0..1       amplitude ratio between consecutive repeats
    taps           1..8       how many repeats are generated
    mix            0..1       dry/wet balance
"""

from __future__ import annotations

import numpy as np

from . import get


def process(x: np.ndarray, params: dict, fs: int = 48000) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    delay_samples = int(get(params, "delay_samples", 12000))
    decay = float(get(params, "decay", 0.5))
    taps = int(get(params, "taps", 4))
    mix = float(get(params, "mix", 0.5))

    if delay_samples <= 0 or taps <= 0:
        return x.copy()

    wet = np.zeros_like(x)
    gain = decay
    for k in range(1, taps + 1):
        shift = delay_samples * k
        if shift >= x.size:
            break
        wet[shift:] += gain * x[: x.size - shift]
        gain *= decay

    return x * (1.0 - mix) + wet * mix
