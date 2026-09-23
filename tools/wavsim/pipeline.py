"""The orchestration layer: wav in, RTL in the middle, wav out.

Everything user-facing (`run`, `chain`, `compare`, the pytest suite) goes through
:func:`process_array`, so there is exactly one description of how audio reaches
the simulator and comes back.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from . import SAMPLE_RATE
from .backends import RunResult, get_backend
from .manifest import Manifest
from .paths import CHAIN_CONFIGS, REPO_ROOT, build_dir
from . import refmodels, resample, stream, wavio


class PipelineError(Exception):
    pass


@dataclass
class StageResult:
    effect: str
    params: Dict
    result: RunResult
    clipped: int = 0


@dataclass
class ChainSpec:
    name: str
    stages: List[Dict] = field(default_factory=list)
    description: str = ""
    path: Optional[Path] = None

    @classmethod
    def load(cls, name_or_path) -> "ChainSpec":
        path = Path(name_or_path)
        if not path.suffix:
            path = CHAIN_CONFIGS / f"{name_or_path}.json"
        if not path.exists():
            available = ", ".join(sorted(p.stem for p in CHAIN_CONFIGS.glob("*.json")))
            raise PipelineError(
                f"no chain config at {path}. Known chains: {available or '(none)'}"
            )
        raw = json.loads(path.read_text())
        if not raw.get("stages"):
            raise PipelineError(f"{path}: chain has no stages")
        return cls(
            name=raw.get("name", path.stem),
            stages=raw["stages"],
            description=raw.get("description", ""),
            path=path,
        )


def load_input(wav_path, fs: int = SAMPLE_RATE) -> np.ndarray:
    """Read a wav as mono float at the project rate.

    Stereo is mixed down: the board's codec is stereo but a guitar input is one
    channel, and every effect here is a single mono instance.
    """
    samples, rate = wavio.read_wav(wav_path, mono=True)
    if rate != fs:
        samples = resample.resample(samples, rate, fs)
    return samples


def process_array(
    manifest: Manifest,
    x: np.ndarray,
    overrides: Optional[Dict] = None,
    backend: str = "auto",
    workdir: Optional[Path] = None,
    cycles_per_sample: Optional[int] = None,
    automation: Optional[Path] = None,
    trace: Optional[Path] = None,
    quiet: bool = True,
) -> Tuple[np.ndarray, RunResult]:
    """Push float samples through the RTL and get float samples back."""
    params = manifest.resolve(overrides)
    sim = get_backend(backend, manifest)

    work = Path(workdir) if workdir else build_dir(manifest.name, sim.name) / "work"
    work.mkdir(parents=True, exist_ok=True)
    in_path = work / "in.pcm24"
    out_path = work / "out.pcm24"

    samples = stream.float_to_samples(x)
    stream.write(in_path, samples, stream.StreamMeta(source=f"{manifest.name} input"))

    result = sim.run(
        in_path,
        out_path,
        params,
        cycles_per_sample=cycles_per_sample,
        automation=automation,
        trace=trace,
        quiet=quiet,
    )
    out_samples = stream.read(out_path)
    result.samples_in = int(samples.size)
    result.samples_out = int(out_samples.size)
    return stream.samples_to_float(out_samples), result


def reference_array(manifest: Manifest, x: np.ndarray, overrides: Optional[Dict] = None,
                    fs: int = SAMPLE_RATE) -> np.ndarray:
    """Run the manifest's float reference model over the same input."""
    model = refmodels.load(manifest.reference_model)
    return model(x, manifest.natural(overrides), fs)


def run_effect(
    effect: str,
    wav_in,
    wav_out=None,
    overrides: Optional[Dict] = None,
    backend: str = "auto",
    fs: int = SAMPLE_RATE,
    max_samples: Optional[int] = None,
    **kwargs,
) -> Tuple[Path, StageResult]:
    """wav -> one effect -> wav."""
    manifest = Manifest.load(effect)
    x = load_input(wav_in, fs)
    if max_samples:
        x = x[:max_samples]
    y, result = process_array(manifest, x, overrides, backend, **kwargs)

    out_path = Path(wav_out) if wav_out else _default_output(wav_in, effect)
    wavio.write_wav(out_path, y, fs)
    clipped = stream.clipped_count(stream.float_to_samples(y))
    return out_path, StageResult(effect, manifest.resolve(overrides), result, clipped)


def run_chain(
    chain: ChainSpec,
    wav_in,
    wav_out=None,
    backend: str = "auto",
    fs: int = SAMPLE_RATE,
    **kwargs,
) -> Tuple[Path, List[StageResult]]:
    """wav -> effect -> effect -> ... -> wav, one board of the mesh per stage.

    Stages are independent simulator runs piped through the sample stream, which
    is the same thing the boards do over their link: each sees only samples.
    """
    x = load_input(wav_in, fs)
    results: List[StageResult] = []

    for position, stage in enumerate(chain.stages):
        if "effect" not in stage:
            raise PipelineError(f"{chain.name}: stage {position} has no 'effect' key")
        manifest = Manifest.load(stage["effect"])
        overrides = stage.get("params", {})
        work = build_dir(manifest.name, "chain") / f"stage{position}"
        x, result = process_array(manifest, x, overrides, backend, workdir=work, **kwargs)
        clipped = stream.clipped_count(stream.float_to_samples(x))
        results.append(StageResult(stage["effect"], manifest.resolve(overrides), result, clipped))

    out_path = Path(wav_out) if wav_out else _default_output(wav_in, chain.name)
    wavio.write_wav(out_path, x, fs)
    return out_path, results


def _default_output(wav_in, suffix: str) -> Path:
    from .paths import ensure_output_dir

    stem = Path(wav_in).stem
    return ensure_output_dir() / f"{stem}_{suffix}.wav"


def temp_workdir(prefix: str = "wavsim") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix + "-"))
