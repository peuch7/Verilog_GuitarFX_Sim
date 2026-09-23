"""WAV reading and writing with no dependencies beyond numpy.

The stdlib ``wave`` module refuses WAVE_FORMAT_EXTENSIBLE (0xFFFE) and float
files, which is what a lot of DAW exports actually are, so reading is done with
a small RIFF parser here. Writing goes out as plain 24-bit PCM, which is what
the codec on the board uses.

Everything in this module speaks float64 in [-1, 1), mono. Conversion to the
24-bit integers the RTL sees happens in :mod:`wavsim.stream`.
"""

from __future__ import annotations

import struct
import wave
from pathlib import Path
from typing import Tuple

import numpy as np

WAVE_FORMAT_PCM = 0x0001
WAVE_FORMAT_IEEE_FLOAT = 0x0003
WAVE_FORMAT_EXTENSIBLE = 0xFFFE


class WavError(Exception):
    pass


def read_wav(path, mono: bool = True) -> Tuple[np.ndarray, int]:
    """Read a WAV file.

    Returns ``(samples, sample_rate)`` where samples is float64 in [-1, 1),
    shape ``(n,)`` when ``mono`` (channels are averaged) or ``(n, channels)``
    otherwise.
    """
    path = Path(path)
    raw = path.read_bytes()
    if len(raw) < 12 or raw[0:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise WavError(f"{path} is not a RIFF/WAVE file")

    fmt = None
    data = None
    pos = 12
    while pos + 8 <= len(raw):
        chunk_id = raw[pos : pos + 4]
        (chunk_size,) = struct.unpack_from("<I", raw, pos + 4)
        body = raw[pos + 8 : pos + 8 + chunk_size]
        if chunk_id == b"fmt ":
            fmt = _parse_fmt(body)
        elif chunk_id == b"data":
            data = body
        pos += 8 + chunk_size + (chunk_size & 1)  # chunks are word aligned

    if fmt is None:
        raise WavError(f"{path} has no fmt chunk")
    if data is None:
        raise WavError(f"{path} has no data chunk")

    samples = _decode(data, fmt)
    if fmt["channels"] > 1:
        samples = samples.reshape(-1, fmt["channels"])
        if mono:
            samples = samples.mean(axis=1)
    return samples, fmt["sample_rate"]


def _parse_fmt(body: bytes) -> dict:
    if len(body) < 16:
        raise WavError("fmt chunk is too short")
    tag, channels, sample_rate, _byte_rate, _align, bits = struct.unpack_from(
        "<HHIIHH", body, 0
    )
    if tag == WAVE_FORMAT_EXTENSIBLE:
        if len(body) < 40:
            raise WavError("WAVE_FORMAT_EXTENSIBLE fmt chunk is too short")
        # The real format is the first two bytes of the SubFormat GUID.
        (tag,) = struct.unpack_from("<H", body, 24)
    if tag not in (WAVE_FORMAT_PCM, WAVE_FORMAT_IEEE_FLOAT):
        raise WavError(
            f"unsupported WAV format tag 0x{tag:04X} (only PCM and IEEE float are handled)"
        )
    return {
        "tag": tag,
        "channels": channels,
        "sample_rate": sample_rate,
        "bits": bits,
    }


def _decode(data: bytes, fmt: dict) -> np.ndarray:
    bits, tag = fmt["bits"], fmt["tag"]

    if tag == WAVE_FORMAT_IEEE_FLOAT:
        dtype = {32: "<f4", 64: "<f8"}.get(bits)
        if dtype is None:
            raise WavError(f"unsupported float width {bits}")
        return np.frombuffer(data, dtype=dtype).astype(np.float64)

    if bits == 8:
        # 8-bit PCM is unsigned by definition.
        return (np.frombuffer(data, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
    if bits == 16:
        return np.frombuffer(data, dtype="<i2").astype(np.float64) / 32768.0
    if bits == 24:
        return _decode_int24(data) / 8388608.0
    if bits == 32:
        return np.frombuffer(data, dtype="<i4").astype(np.float64) / 2147483648.0
    raise WavError(f"unsupported PCM width {bits}")


def _decode_int24(data: bytes) -> np.ndarray:
    """Unpack packed 3-byte little-endian signed samples."""
    n = len(data) // 3
    b = np.frombuffer(data[: n * 3], dtype=np.uint8).reshape(n, 3).astype(np.int32)
    v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
    # Sign extend from bit 23.
    return np.where(v >= 0x800000, v - 0x1000000, v).astype(np.float64)


def write_wav(path, samples: np.ndarray, sample_rate: int, bits: int = 24) -> Path:
    """Write mono float samples as PCM. Values outside [-1, 1) are clipped."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = np.asarray(samples, dtype=np.float64).reshape(-1)

    if bits == 16:
        ints = _quantize(samples, 15)
        payload = ints.astype("<i2").tobytes()
    elif bits == 24:
        ints = _quantize(samples, 23)
        payload = _encode_int24(ints)
    elif bits == 32:
        ints = _quantize(samples, 31)
        payload = ints.astype("<i4").tobytes()
    else:
        raise WavError(f"unsupported output width {bits}")

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(bits // 8)
        w.setframerate(sample_rate)
        w.writeframes(payload)
    return path


def _quantize(samples: np.ndarray, frac_bits: int) -> np.ndarray:
    scale = float(1 << frac_bits)
    ints = np.rint(samples * scale)
    return np.clip(ints, -scale, scale - 1).astype(np.int64)


def _encode_int24(ints: np.ndarray) -> bytes:
    v = (ints.astype(np.int64) & 0xFFFFFF).astype(np.uint32)
    b = np.empty((v.size, 3), dtype=np.uint8)
    b[:, 0] = v & 0xFF
    b[:, 1] = (v >> 8) & 0xFF
    b[:, 2] = (v >> 16) & 0xFF
    return b.tobytes()


def wav_info(path) -> dict:
    """Header summary without decoding the whole file body."""
    path = Path(path)
    samples, rate = read_wav(path, mono=False)
    n = samples.shape[0]
    channels = 1 if samples.ndim == 1 else samples.shape[1]
    return {
        "path": str(path),
        "sample_rate": rate,
        "channels": channels,
        "frames": int(n),
        "seconds": n / rate if rate else 0.0,
        "peak": float(np.max(np.abs(samples))) if n else 0.0,
    }
