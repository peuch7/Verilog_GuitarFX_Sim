"""Rational sample-rate conversion to 48 kHz, numpy only (no scipy).

Polyphase windowed-sinc. For 44100 -> 48000 the ratio reduces to L=160, M=147,
so the prototype filter is L*taps long and is evaluated one phase at a time:

    y[n] = sum_k  h[p + k*L] * x[base - k],   p = m % L, base = m // L, m = n*M + c

``c`` is the prototype's centre, which cancels the filter's group delay so the
output stays time-aligned with the input.
"""

from __future__ import annotations

from math import gcd

import numpy as np

DEFAULT_TAPS = 32
"""Taps per polyphase branch. 32 gives >90 dB stopband with the Kaiser beta below."""

DEFAULT_BETA = 8.6
"""Kaiser beta ~ 8.6 corresponds to roughly -90 dB sidelobes."""

_CHUNK = 65536
"""Output samples per gather block, to bound peak memory at taps*_CHUNK floats."""


def resample(
    x: np.ndarray,
    fs_in: int,
    fs_out: int,
    taps: int = DEFAULT_TAPS,
    beta: float = DEFAULT_BETA,
) -> np.ndarray:
    """Resample ``x`` from ``fs_in`` to ``fs_out``. Returns float64."""
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    if fs_in == fs_out or x.size == 0:
        return x.copy()
    if fs_in <= 0 or fs_out <= 0:
        raise ValueError("sample rates must be positive")

    g = gcd(int(fs_in), int(fs_out))
    up = int(fs_out) // g
    down = int(fs_in) // g

    h = _prototype(up, down, taps, beta)
    n_phase = taps  # taps per branch after the reshape below
    bank = _polyphase_bank(h, up, n_phase)

    centre = (h.size - 1) // 2
    n_out = int(np.floor(x.size * fs_out / fs_in))
    if n_out == 0:
        return np.zeros(0, dtype=np.float64)

    # Pad so that base-k and base stay in range for every output sample.
    pad_left = n_phase
    pad_right = n_phase
    xp = np.concatenate(
        [np.zeros(pad_left), x, np.zeros(pad_right + down)]
    )

    y = np.empty(n_out, dtype=np.float64)
    ks = np.arange(n_phase)
    for start in range(0, n_out, _CHUNK):
        stop = min(start + _CHUNK, n_out)
        n = np.arange(start, stop, dtype=np.int64)
        m = n * down + centre
        phase = m % up
        base = m // up + pad_left
        idx = base[:, None] - ks[None, :]
        np.clip(idx, 0, xp.size - 1, out=idx)
        y[start:stop] = np.einsum("ij,ij->i", bank[phase], xp[idx])
    return y


def _prototype(up: int, down: int, taps: int, beta: float) -> np.ndarray:
    """Lowpass prototype at the upsampled rate, gain-compensated for upsampling."""
    length = up * taps + 1  # odd, so the centre tap is exact
    # Cut off below the lower of the two Nyquist limits, in cycles/sample of the
    # up * fs_in rate. 0.98 leaves a little transition band inside Nyquist.
    cutoff = 0.98 / max(up, down)
    n = np.arange(length) - (length - 1) / 2.0
    h = cutoff * np.sinc(cutoff * n) * np.kaiser(length, beta)
    # Unity passband gain after inserting up-1 zeros between input samples.
    return h * (up / h.sum())


def _polyphase_bank(h: np.ndarray, up: int, taps: int) -> np.ndarray:
    """Split the prototype into ``up`` branches of ``taps`` coefficients each."""
    padded = np.zeros(up * taps, dtype=np.float64)
    padded[: h.size] = h[: up * taps]
    # bank[p, k] == h[p + k*up]
    return padded.reshape(taps, up).T.copy()


def to_project_rate(x: np.ndarray, fs_in: int, fs_out: int = 48000) -> np.ndarray:
    """Convenience wrapper used by the CLI front end."""
    return resample(x, fs_in, fs_out)
