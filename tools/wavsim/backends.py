"""Simulator backends. Both present the same ``run()`` so callers never branch.

Verilator is the default: it compiles the RTL to C++, so a ten second clip runs
in about a second. Icarus is the fallback for anyone who cannot install
Verilator, or whose SystemVerilog Verilator rejects. They are kept
cycle-for-cycle identical on purpose, which is what ``wavsim crosscheck`` checks.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from . import N_PARAMS
from .manifest import Manifest
from .paths import ICARUS_DIR, REPO_ROOT, RTL_COMMON, VERILATOR_DIR, build_dir
from . import stream


class BackendError(Exception):
    pass


@dataclass
class RunResult:
    backend: str
    samples_in: int
    samples_out: int
    latency_cycles: int = -1
    latency_samples: float = -1.0
    cycles: int = 0
    out_stream: Optional[Path] = None
    stats: Dict = field(default_factory=dict)

    def summary(self) -> str:
        latency = (
            f"{self.latency_samples:.2f} samples" if self.latency_samples >= 0 else "unknown"
        )
        return (
            f"{self.backend}: {self.samples_in} in -> {self.samples_out} out, "
            f"latency {latency}"
        )


def _run(cmd: Sequence[str], what: str, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        [str(c) for c in cmd],
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise BackendError(
            f"{what} failed (exit {proc.returncode})\n"
            f"$ {' '.join(str(c) for c in cmd)}\n"
            f"{proc.stdout}\n{proc.stderr}"
        )
    return proc


def _newest(paths: Sequence[Path]) -> float:
    return max((p.stat().st_mtime for p in paths if p.exists()), default=0.0)


class Backend:
    name = "base"

    def __init__(self, manifest: Manifest):
        self.manifest = manifest
        self.dir = build_dir(manifest.name, self.name)

    def available(self) -> bool:
        raise NotImplementedError

    def build(self, trace: bool = False, force: bool = False) -> Path:
        raise NotImplementedError

    def run(
        self,
        in_stream: Path,
        out_stream: Path,
        params: Sequence[int],
        cycles_per_sample: Optional[int] = None,
        flush_samples: Optional[int] = None,
        automation: Optional[Path] = None,
        trace: Optional[Path] = None,
        quiet: bool = True,
    ) -> RunResult:
        raise NotImplementedError

    # Shared helpers ------------------------------------------------------

    def _cps(self, override: Optional[int]) -> int:
        return int(override if override is not None else self.manifest.cycles_per_sample)

    def _flush(self, override: Optional[int]) -> int:
        return int(override if override is not None else self.manifest.flush_samples)

    @staticmethod
    def _check_params(params: Sequence[int]) -> List[int]:
        values = list(params) + [0] * (N_PARAMS - len(params))
        if len(values) > N_PARAMS:
            raise BackendError(f"parameter bus holds {N_PARAMS} slots, got {len(params)}")
        for i, v in enumerate(values):
            if not 0 <= int(v) <= 0xFFFF:
                raise BackendError(f"param slot {i} value {v} outside 0..65535")
        return [int(v) for v in values]

    def _read_stats(self, path: Path, fallback: RunResult) -> RunResult:
        if not path.exists():
            return fallback
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            return fallback
        fallback.stats = data
        fallback.samples_in = int(data.get("samples_in", fallback.samples_in))
        fallback.samples_out = int(data.get("samples_out", fallback.samples_out))
        fallback.cycles = int(data.get("cycles", fallback.cycles))
        fallback.latency_cycles = int(data.get("latency_cycles", fallback.latency_cycles))
        if "latency_samples" in data:
            fallback.latency_samples = float(data["latency_samples"])
        elif fallback.latency_cycles >= 0 and data.get("cycles_per_sample"):
            fallback.latency_samples = fallback.latency_cycles / float(data["cycles_per_sample"])
        return fallback


class VerilatorBackend(Backend):
    name = "verilator"

    def available(self) -> bool:
        return shutil.which("verilator") is not None

    @property
    def _binary(self) -> Path:
        return self.dir / "obj_dir" / f"sim_{self.manifest.name}"

    def build(self, trace: bool = False, force: bool = False) -> Path:
        if not self.available():
            raise BackendError(
                "verilator not found on PATH. Run `make doctor` for install instructions, "
                "or use the Icarus backend with --backend icarus."
            )
        harness = [VERILATOR_DIR / "sim_main.cpp", VERILATOR_DIR / "stream_io.cpp"]
        deps = list(self.manifest.sources) + harness + [VERILATOR_DIR / "stream_io.h"]
        marker = self.dir / "build_flags.json"
        flags = {"trace": bool(trace)}

        stale = (
            force
            or not self._binary.exists()
            or _newest(deps) > self._binary.stat().st_mtime
            or not marker.exists()
            or json.loads(marker.read_text()) != flags
        )
        if not stale:
            return self._binary

        top = self.manifest.top
        cflags = [
            "-std=c++17",
            "-O2",
            f'-DDUT_HEADER=\\"V{top}.h\\"',
            f"-DDUT_TYPE=V{top}",
        ]
        cmd = [
            "verilator",
            "--cc",
            "--exe",
            "--build",
            "-j",
            "0",
            "-Wno-fatal",           # members' width warnings should not block a run
            "--top-module",
            top,
            "--Mdir",
            self.dir / "obj_dir",
            "-o",
            f"sim_{self.manifest.name}",
            f"+incdir+{RTL_COMMON}",
            "-CFLAGS",
            " ".join(cflags),
        ]
        if trace:
            cmd += ["--trace", "--trace-depth", "99"]
        cmd += [str(s) for s in self.manifest.sources]
        cmd += [str(h) for h in harness]

        _run(cmd, f"verilating {self.manifest.name}")
        marker.write_text(json.dumps(flags))
        return self._binary

    def run(
        self,
        in_stream: Path,
        out_stream: Path,
        params: Sequence[int],
        cycles_per_sample: Optional[int] = None,
        flush_samples: Optional[int] = None,
        automation: Optional[Path] = None,
        trace: Optional[Path] = None,
        quiet: bool = True,
    ) -> RunResult:
        values = self._check_params(params)
        binary = self.build(trace=trace is not None)
        stats_path = self.dir / "stats.json"

        cmd = [
            binary,
            "--in", in_stream,
            "--out", out_stream,
            "--params", ",".join(str(v) for v in values),
            "--cycles-per-sample", self._cps(cycles_per_sample),
            "--flush-samples", self._flush(flush_samples),
            "--stats", stats_path,
        ]
        if automation:
            cmd += ["--automation", automation]
        if trace:
            cmd += ["--trace", trace]
        if quiet:
            cmd += ["--quiet"]

        _run(cmd, f"running {self.manifest.name} under verilator")
        result = RunResult(
            backend=self.name,
            samples_in=0,
            samples_out=0,
            out_stream=Path(out_stream),
        )
        return self._read_stats(stats_path, result)


class IcarusBackend(Backend):
    name = "icarus"

    def available(self) -> bool:
        return shutil.which("iverilog") is not None and shutil.which("vvp") is not None

    @property
    def _binary(self) -> Path:
        return self.dir / "sim.vvp"

    def build(self, trace: bool = False, force: bool = False) -> Path:
        if not self.available():
            raise BackendError(
                "iverilog/vvp not found on PATH. Run `make doctor` for install instructions."
            )
        tb = ICARUS_DIR / "tb_top.sv"
        deps = list(self.manifest.sources) + [tb]
        if not force and self._binary.exists() and _newest(deps) <= self._binary.stat().st_mtime:
            return self._binary

        cmd = [
            "iverilog",
            "-g2012",
            f"-DDUT_TOP={self.manifest.top}",
            "-I", RTL_COMMON,
            "-s", "tb_top",
            "-o", self._binary,
            tb,
        ] + [str(s) for s in self.manifest.sources]
        _run(cmd, f"compiling {self.manifest.name} with iverilog")
        return self._binary

    def run(
        self,
        in_stream: Path,
        out_stream: Path,
        params: Sequence[int],
        cycles_per_sample: Optional[int] = None,
        flush_samples: Optional[int] = None,
        automation: Optional[Path] = None,
        trace: Optional[Path] = None,
        quiet: bool = True,
    ) -> RunResult:
        values = self._check_params(params)
        binary = self.build()
        stats_path = self.dir / "stats.json"

        # The SV testbench reads and writes decimal text; convert around it so the
        # canonical on-disk format stays binary int32 for both backends.
        text_in = self.dir / "in.pcm24.txt"
        text_out = self.dir / "out.pcm24.txt"
        stream.write_text(text_in, stream.read(in_stream))

        cmd = [
            "vvp", binary,
            f"+in={text_in}",
            f"+out={text_out}",
            f"+cps={self._cps(cycles_per_sample)}",
            f"+flush={self._flush(flush_samples)}",
            f"+stats={stats_path}",
        ] + [f"+p{i}={v}" for i, v in enumerate(values)]
        if automation:
            cmd.append(f"+automation={automation}")

        proc = _run(cmd, f"running {self.manifest.name} under icarus")
        if not quiet and proc.stdout:
            print(proc.stdout.strip())

        samples = stream.read_text(text_out)
        stream.write(out_stream, samples)

        result = RunResult(
            backend=self.name,
            samples_in=0,
            samples_out=int(samples.size),
            out_stream=Path(out_stream),
        )
        return self._read_stats(stats_path, result)


BACKENDS = {"verilator": VerilatorBackend, "icarus": IcarusBackend}


def get_backend(name: str, manifest: Manifest) -> Backend:
    if name == "auto":
        for candidate in ("verilator", "icarus"):
            backend = BACKENDS[candidate](manifest)
            if backend.available():
                return backend
        raise BackendError(
            "no simulator found. Install Verilator or Icarus (see `make doctor`), "
            "or use the container: `make docker-build`."
        )
    if name not in BACKENDS:
        raise BackendError(f"unknown backend {name!r}; choose from auto, verilator, icarus")
    return BACKENDS[name](manifest)
