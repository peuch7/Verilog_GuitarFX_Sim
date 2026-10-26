
"""Reference model for adjustable first-order IIR low-pass filter.

Matches the SystemVerilog Q15 fixed-point implementation.
"""

from __future__ import annotations

import numpy as np

from . import get


def process(x: np.ndarray, params: dict, fs: int = 48000) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64).reshape(-1)

    # Read the cutoff frequency
    cutoff_hz = int(params.get("cutoff_hz", 1000))
    cutoff_hz = max(100, min(10000, cutoff_hz))

    # Match the SystemVerilog Q15 coefficient
    alpha_q15 = (cutoff_hz * 32768) // (cutoff_hz + 7639)

    # Convert normalized audio to 24-bit signed integers
    scale = 2**23
    x_int = np.clip(
        np.rint(x * scale),
        -(2**23),
        2**23 - 1
    ).astype(np.int64)

    # Apply the filter
    y_int = np.zeros(len(x_int), dtype=np.int64)
    y_prev = 0

    for n, sample in enumerate(x_int):
        difference = int(sample) - y_prev
        increment = (difference * alpha_q15) >> 15

        y_prev += increment
        y_int[n] = y_prev

    # Convert back into normalized floating-point audio
    return y_int.astype(np.float64) / scale
