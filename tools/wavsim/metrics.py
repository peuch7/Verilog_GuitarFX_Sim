"""Turning "it sounds right" into numbers.

The comparison that matters is RTL output against the float reference model. Raw
sample-by-sample difference is not enough on its own, because a design that is
correct but delayed by one sample looks catastrophically wrong, so alignment is
found first and reported separately. Read the results together:

    lag             a constant offset is usually pipeline latency, not a bug
    snr_db          error energy vs reference energy; the headline number
    max_abs_error   worst single sample, in LSBs of the 24-bit word
    clipped         samples sitting on a rail, a sign a stage overflows
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import numpy as np

from . import SAMPLE_SCALE


@dataclass
class Comparison:
    n_ref: int
    n_test: int
    lag: int
    n_compared: int
    snr_db: float
    max_abs_error: float
    max_abs_error_lsb: float
    rms_error: float
    ref_rms: float
    test_rms: float
    correlation: float
    clipped: int = 0
    notes: list = field(default_factory=list)

    def as_dict(self) -> Dict:
        return {
            "n_ref": self.n_ref,
            "n_test": self.n_test,
            "lag": self.lag,
            "n_compared": self.n_compared,
            "snr_db": self.snr_db,
            "max_abs_error": self.max_abs_error,
            "max_abs_error_lsb": self.max_abs_error_lsb,
            "rms_error": self.rms_error,
            "ref_rms": self.ref_rms,
            "test_rms": self.test_rms,
            "correlation": self.correlation,
            "clipped": self.clipped,
            "notes": self.notes,
        }

    def report(self) -> str:
        lines = [
            f"  samples        ref {self.n_ref}, rtl {self.n_test}, compared {self.n_compared}",
            f"  lag            {self.lag} samples"
            + ("  (RTL later than reference)" if self.lag > 0 else ""),
            f"  SNR            {self.snr_db:.1f} dB",
            f"  max error      {self.max_abs_error:.3e}  ({self.max_abs_error_lsb:.1f} LSB of 24-bit)",
            f"  rms error      {self.rms_error:.3e}",
            f"  correlation    {self.correlation:.6f}",
            f"  levels         ref rms {_db(self.ref_rms):.1f} dBFS, rtl rms {_db(self.test_rms):.1f} dBFS",
        ]
        if self.clipped:
            lines.append(f"  clipped        {self.clipped} samples on a rail")
        for note in self.notes:
            lines.append(f"  note           {note}")
        return "\n".join(lines)


def _db(x: float) -> float:
    return 20.0 * np.log10(x) if x > 0 else -np.inf


def find_lag(ref: np.ndarray, test: np.ndarray, max_lag: int = 4096) -> int:
    """Integer lag that best aligns ``test`` onto ``ref``, by cross-correlation.

    Positive means the RTL output arrives later than the reference. Only a
    leading window is used, which keeps this quick on long clips and is where
    latency is visible anyway.
    """
    n = int(min(ref.size, test.size, 1 << 16))
    if n == 0:
        return 0
    a = ref[:n] - ref[:n].mean()
    b = test[:n] - test[:n].mean()
    if not np.any(a) or not np.any(b):
        return 0

    size = 1 << int(np.ceil(np.log2(2 * n)))
    corr = np.fft.irfft(np.fft.rfft(b, size) * np.conj(np.fft.rfft(a, size)), size)
    limit = int(min(max_lag, n - 1))
    # Lags 0..limit live at the front, negative lags wrap to the back.
    candidates = np.concatenate([corr[: limit + 1], corr[-limit:]]) if limit else corr[:1]
    lags = np.concatenate([np.arange(limit + 1), np.arange(-limit, 0)]) if limit else np.array([0])
    return int(lags[int(np.argmax(candidates))])


def compare(
    ref: np.ndarray,
    test: np.ndarray,
    align: bool = True,
    lag: Optional[int] = None,
    clipped: int = 0,
) -> Comparison:
    """Compare a reference signal against RTL output, aligning them first."""
    ref = np.asarray(ref, dtype=np.float64).reshape(-1)
    test = np.asarray(test, dtype=np.float64).reshape(-1)
    notes = []

    if lag is None:
        lag = find_lag(ref, test) if align else 0

    if lag > 0:
        a, b = ref[: ref.size - lag], test[lag:]
    elif lag < 0:
        a, b = ref[-lag:], test[: test.size + lag]
    else:
        a, b = ref, test

    n = int(min(a.size, b.size))
    a, b = a[:n], b[:n]

    if n == 0:
        notes.append("no overlapping samples to compare")
        return Comparison(ref.size, test.size, lag, 0, -np.inf, np.inf, np.inf,
                          np.inf, 0.0, 0.0, 0.0, clipped, notes)

    err = b - a
    ref_energy = float(np.sum(a * a))
    err_energy = float(np.sum(err * err))
    if err_energy == 0.0:
        snr = np.inf
        notes.append("bit-exact match against the reference")
    elif ref_energy == 0.0:
        snr = -np.inf
        notes.append("reference is silent but the RTL output is not")
    else:
        snr = 10.0 * np.log10(ref_energy / err_energy)

    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    corr = float(np.dot(a, b) / denom) if denom > 0 else 0.0

    max_err = float(np.max(np.abs(err)))
    return Comparison(
        n_ref=int(ref.size),
        n_test=int(test.size),
        lag=int(lag),
        n_compared=n,
        snr_db=float(snr),
        max_abs_error=max_err,
        max_abs_error_lsb=max_err * SAMPLE_SCALE,
        rms_error=float(np.sqrt(err_energy / n)),
        ref_rms=float(np.sqrt(ref_energy / n)),
        test_rms=float(np.sqrt(np.sum(b * b) / n)),
        correlation=corr,
        clipped=clipped,
        notes=notes,
    )


def thd_db(x: np.ndarray, fs: int, f0: float, harmonics: int = 8) -> float:
    """Total harmonic distortion of a sine, in dB relative to the fundamental.

    Useful for the distortion and overdrive owners: it puts a number on how much
    harmonic content a drive setting actually generates.
    """
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    if x.size < 16:
        return -np.inf
    window = np.hanning(x.size)
    spec = np.abs(np.fft.rfft(x * window))
    freqs = np.fft.rfftfreq(x.size, 1.0 / fs)

    def bin_energy(target: float) -> float:
        if target >= freqs[-1]:
            return 0.0
        centre = int(np.argmin(np.abs(freqs - target)))
        lo, hi = max(centre - 2, 0), min(centre + 3, spec.size)
        return float(np.sum(spec[lo:hi] ** 2))

    fundamental = bin_energy(f0)
    if fundamental <= 0:
        return -np.inf
    harmonic_energy = sum(bin_energy(f0 * k) for k in range(2, harmonics + 1))
    if harmonic_energy <= 0:
        return -np.inf
    return 10.0 * np.log10(harmonic_energy / fundamental)


def impulse_peak(y: np.ndarray, skip: int = 0) -> tuple:
    """Index and value of the largest magnitude sample, used by the delay tests."""
    y = np.asarray(y).reshape(-1)
    if y.size <= skip:
        return -1, 0.0
    idx = int(np.argmax(np.abs(y[skip:]))) + skip
    return idx, float(y[idx])
