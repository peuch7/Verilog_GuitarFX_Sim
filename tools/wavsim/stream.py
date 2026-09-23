"""The sample stream that flows between Python, the simulators, and back.

Canonical form is raw little-endian int32, one per sample, holding values
sign-extended from the signed 24-bit range. int32 rather than packed 3-byte
because every consumer reads it in one line:

    numpy   np.fromfile(path, dtype="<i4")
    C++     fread(buf, 4, n, f)
    SV      $fread on a 32-bit word

A ``<name>.meta.json`` sidecar records rate, count and provenance so the back
end can rebuild a wav without being told anything.

``write_text``/``read_text`` are the same data in decimal, used only when the
Icarus backend needs it; see sim/STREAM_FORMAT.md.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from . import SAMPLE_MAX, SAMPLE_MIN, SAMPLE_RATE, SAMPLE_SCALE

DTYPE = np.dtype("<i4")


@dataclass
class StreamMeta:
    sample_rate: int = SAMPLE_RATE
    n_samples: int = 0
    width: int = 24
    source: str = ""
    notes: dict = field(default_factory=dict)

    def path_for(self, stream_path) -> Path:
        return Path(str(stream_path) + ".meta.json")

    def save(self, stream_path) -> Path:
        p = self.path_for(stream_path)
        p.write_text(json.dumps(asdict(self), indent=2) + "\n")
        return p

    @classmethod
    def load(cls, stream_path) -> "StreamMeta":
        p = Path(str(stream_path) + ".meta.json")
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text())
        known = {k: raw[k] for k in raw if k in cls.__dataclass_fields__}
        return cls(**known)


def float_to_samples(x: np.ndarray) -> np.ndarray:
    """float64 in [-1, 1) -> int32 holding signed 24-bit values, clipped."""
    ints = np.rint(np.asarray(x, dtype=np.float64) * SAMPLE_SCALE)
    return np.clip(ints, SAMPLE_MIN, SAMPLE_MAX).astype(DTYPE)


def samples_to_float(a: np.ndarray) -> np.ndarray:
    """Signed 24-bit integers -> float64 in [-1, 1). Exact round trip."""
    return np.asarray(a, dtype=np.float64) / SAMPLE_SCALE


def write(path, samples: np.ndarray, meta: Optional[StreamMeta] = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(samples, dtype=DTYPE)
    if arr.size and (arr.max() > SAMPLE_MAX or arr.min() < SAMPLE_MIN):
        raise ValueError(
            "stream values outside the signed 24-bit range; "
            "use float_to_samples() or clip before writing"
        )
    arr.tofile(str(path))
    meta = meta or StreamMeta()
    meta.n_samples = int(arr.size)
    meta.save(path)
    return path


def read(path) -> np.ndarray:
    return np.fromfile(str(path), dtype=DTYPE)


def write_text(path, samples: np.ndarray) -> Path:
    """Decimal, one sample per line, for simulators that dislike binary I/O."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savetxt(str(path), np.asarray(samples, dtype=DTYPE), fmt="%d")
    return path


def read_text(path) -> np.ndarray:
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        return np.zeros(0, dtype=DTYPE)
    arr = np.loadtxt(str(p), dtype=np.int64, ndmin=1)
    return arr.astype(DTYPE)


def clipped_count(samples: np.ndarray) -> int:
    """How many samples sit exactly on a rail: a hint that a stage is overflowing."""
    a = np.asarray(samples)
    return int(np.count_nonzero((a >= SAMPLE_MAX) | (a <= SAMPLE_MIN)))
