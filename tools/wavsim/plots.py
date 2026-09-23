"""Optional plots for `wavsim compare --plot`.

matplotlib is a dev extra, not a runtime dependency, so this module must never be
imported at startup — only when a plot is actually asked for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from . import SAMPLE_RATE


class PlotError(Exception):
    pass


def _pyplot():
    try:
        import matplotlib
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise PlotError(
            "matplotlib is not installed. Run: pip install -e \".[dev]\""
        ) from exc
    matplotlib.use("Agg")  # no display inside a container or over ssh
    import matplotlib.pyplot as plt

    return plt


def compare_plot(
    ref: np.ndarray,
    test: np.ndarray,
    path,
    fs: int = SAMPLE_RATE,
    title: str = "RTL vs reference",
    lag: int = 0,
    zoom_ms: float = 20.0,
) -> Path:
    """Waveform overlay, error trace, and both spectrograms in one figure."""
    plt = _pyplot()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    ref = np.asarray(ref, dtype=np.float64).reshape(-1)
    test = np.asarray(test, dtype=np.float64).reshape(-1)
    if lag > 0:
        test = test[lag:]
    elif lag < 0:
        ref = ref[-lag:]
    n = int(min(ref.size, test.size))
    ref, test = ref[:n], test[:n]
    t = np.arange(n) / fs

    fig, axes = plt.subplots(4, 1, figsize=(11, 10), constrained_layout=True)
    fig.suptitle(title)

    # Drawing every cycle of a whole clip fills the panel with solid ink, which
    # shows nothing. Zoom the waveform overlay to a window where individual
    # cycles are visible, centred on the worst error so the zoom lands somewhere
    # interesting rather than on a quiet intro.
    err = test - ref
    window = min(n, int(fs * zoom_ms / 1000.0))
    centre = int(np.argmax(np.abs(err))) if n else 0
    start = int(np.clip(centre - window // 2, 0, max(n - window, 0)))
    stop = start + window
    zoom = slice(start, stop)

    axes[0].plot(t[zoom], ref[zoom], linewidth=0.8, label="reference")
    axes[0].plot(t[zoom], test[zoom], linewidth=0.8, alpha=0.75, label="RTL")
    axes[0].set_ylabel("amplitude")
    axes[0].legend(loc="upper right")
    shifted = f", RTL shifted back {lag} samples" if lag else ""
    axes[0].set_title(
        f"waveforms — {zoom_ms:g} ms around the worst error at {t[centre] if n else 0:.3f} s{shifted}"
    )

    # The error panel stays full length: its envelope over time is the thing
    # worth seeing, and it shows whether the error grows or stays bounded.
    axes[1].plot(t, err, linewidth=0.6, color="crimson")
    axes[1].axvspan(t[start], t[stop - 1] if stop else 0, color="black", alpha=0.08)
    axes[1].set_ylabel("error")
    peak = float(np.max(np.abs(err))) if n else 0.0
    axes[1].set_title(f"error over the whole clip, peak {peak:.2e} (shaded = panel above)")

    for ax, data, name in ((axes[2], ref, "reference"), (axes[3], test, "RTL")):
        if n >= 256:
            ax.specgram(data, NFFT=1024, Fs=fs, noverlap=512, cmap="magma")
        ax.set_ylabel("Hz")
        ax.set_title(f"{name} spectrogram")
    axes[3].set_xlabel("seconds")

    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def waveform_plot(x: np.ndarray, path, fs: int = SAMPLE_RATE,
                  title: str = "signal", label: Optional[str] = None) -> Path:
    """A single waveform plus its spectrogram, for eyeballing one run."""
    plt = _pyplot()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    x = np.asarray(x, dtype=np.float64).reshape(-1)
    t = np.arange(x.size) / fs

    fig, axes = plt.subplots(2, 1, figsize=(11, 6), constrained_layout=True)
    fig.suptitle(title)
    axes[0].plot(t, x, linewidth=0.6, label=label)
    axes[0].set_ylabel("amplitude")
    if label:
        axes[0].legend(loc="upper right")
    if x.size >= 256:
        axes[1].specgram(x, NFFT=1024, Fs=fs, noverlap=512, cmap="magma")
    axes[1].set_ylabel("Hz")
    axes[1].set_xlabel("seconds")

    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path
