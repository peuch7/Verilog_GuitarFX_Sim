"""Synthetic test signals, so the repo needs no committed audio to be useful.

Each one answers a different question:

    impulse     what is the impulse response? (delay taps land exactly here)
    step        is there a DC offset or a settling problem?
    sine        harmonic distortion, gain accuracy
    sweep       frequency response across the band
    noise       a broadband worst case for overflow
    pluck       a real guitar-shaped transient, for listening to
"""

from __future__ import annotations

import numpy as np

from . import SAMPLE_RATE


def silence(seconds: float = 1.0, fs: int = SAMPLE_RATE) -> np.ndarray:
    return np.zeros(int(seconds * fs), dtype=np.float64)


def impulse(seconds: float = 1.0, fs: int = SAMPLE_RATE, amplitude: float = 0.9,
            position: int = 0) -> np.ndarray:
    x = np.zeros(int(seconds * fs), dtype=np.float64)
    if 0 <= position < x.size:
        x[position] = amplitude
    return x


def step(seconds: float = 1.0, fs: int = SAMPLE_RATE, amplitude: float = 0.5) -> np.ndarray:
    x = np.zeros(int(seconds * fs), dtype=np.float64)
    x[x.size // 4:] = amplitude
    return x


def sine(freq: float = 1000.0, seconds: float = 1.0, fs: int = SAMPLE_RATE,
         amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(int(seconds * fs), dtype=np.float64) / fs
    return amplitude * np.sin(2.0 * np.pi * freq * t)


def sweep(f0: float = 20.0, f1: float = 20000.0, seconds: float = 4.0,
          fs: int = SAMPLE_RATE, amplitude: float = 0.5) -> np.ndarray:
    """Logarithmic sine sweep, with short fades so the ends do not click."""
    n = int(seconds * fs)
    t = np.arange(n, dtype=np.float64) / fs
    f1 = min(f1, fs / 2.0 * 0.98)
    k = np.log(f1 / f0)
    phase = 2.0 * np.pi * f0 * seconds / k * (np.exp(t * k / seconds) - 1.0)
    x = amplitude * np.sin(phase)
    return _fade(x, fs)


def noise(seconds: float = 1.0, fs: int = SAMPLE_RATE, amplitude: float = 0.3,
          seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return amplitude * rng.standard_normal(int(seconds * fs))


def pluck(freq: float = 82.41, seconds: float = 2.0, fs: int = SAMPLE_RATE,
          amplitude: float = 0.6, damping: float = 0.996, seed: int = 0) -> np.ndarray:
    """One plucked string via Karplus-Strong.

    A short noise burst circulates through a delay line of one period with a
    two-point average in the loop, so the highs decay faster than the
    fundamental. That is close enough to a real pluck to make delay and reverb
    settings audibly meaningful, and the default 82.41 Hz is a low E.
    """
    n = int(seconds * fs)
    period = max(int(round(fs / freq)), 2)
    rng = np.random.default_rng(seed)
    buf = rng.standard_normal(period)
    buf /= np.max(np.abs(buf))

    out = np.empty(n, dtype=np.float64)
    idx = 0
    prev = 0.0
    for i in range(n):
        current = buf[idx]
        out[i] = current
        buf[idx] = damping * 0.5 * (current + prev)
        prev = current
        idx += 1
        if idx == period:
            idx = 0

    out *= amplitude * np.exp(-np.arange(n) / (0.9 * n))
    return _fade(out, fs)


def guitar_phrase(fs: int = SAMPLE_RATE, seed: int = 0) -> np.ndarray:
    """An E-minor arpeggio of plucks — the demo clip for listening tests."""
    notes = [82.41, 123.47, 164.81, 196.00, 246.94, 329.63]  # E2 B2 E3 G3 B3 E4
    spacing = int(0.35 * fs)
    total = spacing * len(notes) + int(2.0 * fs)
    out = np.zeros(total, dtype=np.float64)
    for i, freq in enumerate(notes):
        note = pluck(freq, seconds=2.0, fs=fs, amplitude=0.5, seed=seed + i)
        start = i * spacing
        out[start:start + note.size] += note[: max(0, total - start)]
    peak = np.max(np.abs(out))
    if peak > 0:
        out *= 0.7 / peak
    return out


def _fade(x: np.ndarray, fs: int, ms: float = 5.0) -> np.ndarray:
    n = min(int(fs * ms / 1000.0), x.size // 2)
    if n <= 0:
        return x
    ramp = np.linspace(0.0, 1.0, n)
    x = x.copy()
    x[:n] *= ramp
    x[-n:] *= ramp[::-1]
    return x


CATALOG = {
    "impulse": lambda fs: impulse(1.0, fs),
    "step": lambda fs: step(0.5, fs),
    "sine1k": lambda fs: sine(1000.0, 1.0, fs),
    "sweep": lambda fs: sweep(20.0, 20000.0, 4.0, fs),
    "noise": lambda fs: noise(1.0, fs),
    "pluck": lambda fs: pluck(82.41, 2.0, fs),
    "guitar": lambda fs: guitar_phrase(fs),
}


def generate(name: str, fs: int = SAMPLE_RATE) -> np.ndarray:
    if name not in CATALOG:
        raise KeyError(f"unknown signal {name!r}; choose from {', '.join(sorted(CATALOG))}")
    return CATALOG[name](fs)
