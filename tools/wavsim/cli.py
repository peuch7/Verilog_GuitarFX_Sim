"""Command line entry point: ``python -m wavsim <command>`` or ``wavsim <command>``.

The Makefile and wavsim.ps1 are thin wrappers over this, so there is one place
that defines what the tool can do.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import numpy as np

from . import SAMPLE_RATE
from .backends import BackendError, get_backend
from .manifest import Manifest, ManifestError, parse_param_items
from .paths import AUDIO_IN, EFFECT_CONFIGS, CHAIN_CONFIGS, REPO_ROOT, RTL_COMMON, build_dir
from .pipeline import (
    ChainSpec,
    PipelineError,
    load_input,
    process_array,
    reference_array,
    run_chain,
    run_effect,
)
from . import metrics, signals, stream, wavio


# ---------------------------------------------------------------------------
# helpers


def _input_signal(args) -> "tuple[np.ndarray, str]":
    """Either a wav from disk or one of the synthetic test signals."""
    if getattr(args, "wav", None):
        return load_input(args.wav), Path(args.wav).stem
    name = getattr(args, "signal", None) or "sweep"
    return signals.generate(name), name


def _overrides(args) -> dict:
    return parse_param_items(getattr(args, "param", None))


def _print_stage(label: str, result) -> None:
    print(f"  {label:<14} {result.result.summary()}")
    if result.clipped:
        print(f"  {'':<14} {result.clipped} output samples hit a rail (possible overflow)")


# ---------------------------------------------------------------------------
# commands


def cmd_run(args) -> int:
    overrides = _overrides(args)
    manifest = Manifest.load(args.effect)

    if args.wav:
        wav_in = Path(args.wav)
    else:
        wav_in = _ensure_demo_audio(args.signal or "guitar")

    out_path, stage = run_effect(
        args.effect,
        wav_in,
        args.out,
        overrides,
        backend=args.backend,
        max_samples=args.max_samples,
        cycles_per_sample=args.cycles_per_sample,
        automation=Path(args.automation) if args.automation else None,
        trace=Path(args.trace) if args.trace else None,
        quiet=not args.verbose,
    )

    print(f"{args.effect}: {wav_in} -> {out_path}")
    print(f"  params         {_params_text(manifest, overrides)}")
    _print_stage(args.effect, stage)
    if args.trace:
        print(f"  trace          {args.trace}")
    return 0


def cmd_chain(args) -> int:
    chain = ChainSpec.load(args.config)
    wav_in = Path(args.wav) if args.wav else _ensure_demo_audio("guitar")

    out_path, results = run_chain(
        chain, wav_in, args.out, backend=args.backend, quiet=not args.verbose
    )
    print(f"chain {chain.name}: {wav_in} -> {out_path}")
    if chain.description:
        print(f"  {chain.description}")
    for i, stage in enumerate(results):
        _print_stage(f"[{i}] {stage.effect}", stage)
    return 0


def cmd_compare(args) -> int:
    manifest = Manifest.load(args.effect)
    overrides = _overrides(args)
    x, source = _input_signal(args)

    rtl, result = process_array(
        manifest, x, overrides, backend=args.backend, quiet=not args.verbose
    )
    try:
        ref = reference_array(manifest, x, overrides)
    except Exception as exc:
        print(f"error: reference model failed: {exc}", file=sys.stderr)
        return 1

    clipped = stream.clipped_count(stream.float_to_samples(rtl))
    comparison = metrics.compare(ref, rtl, align=not args.no_align, clipped=clipped)

    print(f"compare {args.effect} on {source}")
    print(f"  params         {_params_text(manifest, overrides)}")
    print(f"  backend        {result.backend}")
    print(comparison.report())

    if args.plot:
        from .plots import compare_plot

        path = Path(args.plot)
        compare_plot(ref, rtl, path, title=f"{args.effect} — RTL vs reference",
                     lag=comparison.lag)
        print(f"  plot           {path}")

    if args.json:
        Path(args.json).write_text(json.dumps(comparison.as_dict(), indent=2) + "\n")
        print(f"  json           {args.json}")

    if args.min_snr is not None and comparison.snr_db < args.min_snr:
        print(
            f"\nFAIL: SNR {comparison.snr_db:.1f} dB is below the {args.min_snr:.1f} dB threshold",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_crosscheck(args) -> int:
    """Run both simulators on identical input and diff the streams."""
    manifest = Manifest.load(args.effect)
    overrides = _overrides(args)
    x, source = _input_signal(args)
    if args.max_samples:
        x = x[: args.max_samples]

    outputs = {}
    for backend in ("verilator", "icarus"):
        sim = get_backend(backend, manifest)
        if not sim.available():
            print(f"error: {backend} is not installed; crosscheck needs both", file=sys.stderr)
            return 2
        y, result = process_array(
            manifest, x, overrides, backend=backend,
            workdir=build_dir(manifest.name, backend) / "crosscheck",
            quiet=not args.verbose,
        )
        outputs[backend] = stream.float_to_samples(y)
        print(f"  {result.summary()}")

    a, b = outputs["verilator"], outputs["icarus"]
    print(f"crosscheck {args.effect} on {source}")
    if a.size != b.size:
        print(f"  MISMATCH: verilator produced {a.size} samples, icarus {b.size}", file=sys.stderr)
        return 1
    if not np.array_equal(a, b):
        diff = np.nonzero(a != b)[0]
        print(
            f"  MISMATCH: {diff.size} of {a.size} samples differ, first at index {diff[0]}",
            file=sys.stderr,
        )
        return 1
    print(f"  OK: both simulators produced {a.size} identical samples")
    return 0


# Warnings that are structural to this project rather than mistakes: a wrapper
# always exposes all 8 parameter slots even when the effect uses three, and the
# scaffolded stubs do not read their knobs yet. Left on, they would bury the
# width and truncation warnings that actually matter in fixed-point audio.
LINT_SUPPRESS = ("UNUSEDSIGNAL", "UNUSEDPARAM", "DECLFILENAME", "EOFNEWLINE")


def cmd_lint(args) -> int:
    names = [args.effect] if args.effect else Manifest.list_effects()
    failures = 0
    for name in names:
        manifest = Manifest.load(name)
        cmd = ["verilator", "--lint-only", "-Wall"]
        if not args.strict:
            # Report warnings but only fail on real errors, so lint stays usable
            # on a teammate's work in progress.
            cmd.append("-Wno-fatal")
            cmd += [f"-Wno-{w}" for w in LINT_SUPPRESS]
        cmd += ["--top-module", manifest.top, f"+incdir+{RTL_COMMON}"]
        cmd += [str(s) for s in manifest.sources]

        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
        warnings = proc.stderr.count("%Warning")
        if proc.returncode != 0:
            status = "FAILED"
            failures += 1
        elif warnings:
            status = f"ok ({warnings} warning{'s' if warnings != 1 else ''})"
        else:
            status = "ok"
        print(f"{name:<12} {status}")
        if proc.stderr.strip() and (warnings or proc.returncode != 0):
            print(proc.stderr.rstrip())
    return 1 if failures else 0


def cmd_list(args) -> int:
    print("effects:")
    for name in Manifest.list_effects():
        m = Manifest.load(name)
        owner = f" ({m.owner})" if m.owner else ""
        print(f"  {name:<12}{owner:<16} {m.description}")
    chains = sorted(CHAIN_CONFIGS.glob("*.json"))
    if chains:
        print("\nchains:")
        for path in chains:
            chain = ChainSpec.load(path)
            stages = " -> ".join(s["effect"] for s in chain.stages)
            print(f"  {chain.name:<12} {stages}")
    return 0


def cmd_info(args) -> int:
    m = Manifest.load(args.effect)
    print(f"{m.name}  (top module {m.top})")
    if m.owner:
        print(f"  owner          {m.owner}")
    if m.description:
        print(f"  description    {m.description}")
    print(f"  manifest       {m.path}")
    print(f"  sources        {', '.join(str(s.relative_to(REPO_ROOT)) for s in m.sources)}")
    print(f"  timing         {m.cycles_per_sample} clocks/sample, flush {m.flush_samples} samples")
    print(f"  model          {m.reference_model or '(none)'}")
    print("  parameters:")
    print(m.describe_params())
    return 0


def cmd_new_effect(args) -> int:
    from .scaffold import ParamSpec, create_effect

    params = []
    for i, name in enumerate(args.param or []):
        scale = "raw"
        if ":" in name:
            name, scale = name.split(":", 1)
        params.append(ParamSpec(name=name, index=i, default=0, scale=scale))

    created = create_effect(
        args.name,
        params=params,
        owner=args.owner or "",
        description=args.description or "",
        force=args.force,
    )
    if not created:
        print(f"{args.name}: every file already exists (use --force to overwrite)")
        return 0
    print(f"created {args.name}:")
    for path in created:
        print(f"  {path.relative_to(REPO_ROOT)}")
    print(
        f"\nIt is a passthrough for now, but it already runs:\n"
        f"  wavsim run --effect {args.name}"
    )
    return 0


def cmd_gen_audio(args) -> int:
    AUDIO_IN.mkdir(parents=True, exist_ok=True)
    names = args.signal or ["sweep", "guitar", "impulse", "sine1k"]
    for name in names:
        x = signals.generate(name, SAMPLE_RATE)
        path = AUDIO_IN / f"{name}.wav"
        wavio.write_wav(path, x, SAMPLE_RATE)
        print(f"  {path.relative_to(REPO_ROOT)}  ({x.size / SAMPLE_RATE:.2f} s)")
    return 0


def cmd_doctor(args) -> int:
    script = REPO_ROOT / "scripts" / "doctor.py"
    return subprocess.call([sys.executable, str(script)])


def _ensure_demo_audio(name: str) -> Path:
    """Make the demo wav on demand, so no audio has to be committed."""
    path = AUDIO_IN / f"{name}.wav"
    if not path.exists():
        AUDIO_IN.mkdir(parents=True, exist_ok=True)
        wavio.write_wav(path, signals.generate(name, SAMPLE_RATE), SAMPLE_RATE)
        print(f"generated {path.relative_to(REPO_ROOT)}")
    return path


def _params_text(manifest: Manifest, overrides: dict) -> str:
    natural = manifest.natural(overrides)
    return ", ".join(
        f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in natural.items()
    ) or "(none)"


# ---------------------------------------------------------------------------
# argument parsing


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wavsim",
        description="Simulate a SystemVerilog guitar effect end to end on real audio.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_backend(sp):
        sp.add_argument("--backend", default="auto", choices=["auto", "verilator", "icarus"],
                        help="simulator to use (default: verilator if installed)")
        sp.add_argument("-v", "--verbose", action="store_true", help="show simulator output")

    def add_params(sp):
        sp.add_argument("--param", "-p", action="append", metavar="NAME=VALUE",
                        help="set a knob; repeatable, or comma separated. "
                             "A decimal value is in natural units, an integer is raw bits.")

    # run
    sp = sub.add_parser("run", help="wav -> effect -> wav")
    sp.add_argument("--effect", "-e", required=True)
    sp.add_argument("--wav", "-i", help="input wav (default: the generated demo clip)")
    sp.add_argument("--signal", help="use a synthetic signal instead of a wav")
    sp.add_argument("--out", "-o", help="output wav (default: audio/output/<stem>_<effect>.wav)")
    sp.add_argument("--cycles-per-sample", type=int, help="override the manifest value")
    sp.add_argument("--max-samples", type=int,
                    help="only process the first N samples; keeps VCDs small")
    sp.add_argument("--automation", help="parameter automation file")
    sp.add_argument("--trace", help="write a VCD here (rebuilds with tracing enabled)")
    add_params(sp)
    add_backend(sp)
    sp.set_defaults(func=cmd_run)

    # chain
    sp = sub.add_parser("chain", help="wav -> several effects in series -> wav")
    sp.add_argument("--config", "-c", required=True, help="chain name or path to its json")
    sp.add_argument("--wav", "-i")
    sp.add_argument("--out", "-o")
    add_backend(sp)
    sp.set_defaults(func=cmd_chain)

    # compare
    sp = sub.add_parser("compare", help="RTL output vs the float reference model")
    sp.add_argument("--effect", "-e", required=True)
    sp.add_argument("--wav", "-i")
    sp.add_argument("--signal", default="sweep",
                    help=f"synthetic input: {', '.join(sorted(signals.CATALOG))}")
    sp.add_argument("--plot", help="write a comparison png here")
    sp.add_argument("--json", help="write the metrics as json here")
    sp.add_argument("--min-snr", type=float, help="exit non-zero below this SNR in dB")
    sp.add_argument("--no-align", action="store_true",
                    help="do not compensate for pipeline latency before comparing")
    add_params(sp)
    add_backend(sp)
    sp.set_defaults(func=cmd_compare)

    # crosscheck
    sp = sub.add_parser("crosscheck", help="verify Verilator and Icarus agree exactly")
    sp.add_argument("--effect", "-e", required=True)
    sp.add_argument("--wav", "-i")
    sp.add_argument("--signal", default="noise")
    sp.add_argument("--max-samples", type=int, default=20000,
                    help="cap the length, since Icarus is slow (default 20000)")
    add_params(sp)
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_crosscheck)

    # lint
    sp = sub.add_parser("lint", help="verilator --lint-only over the effects")
    sp.add_argument("--effect", "-e", help="just this one (default: all)")
    sp.add_argument("--strict", action="store_true",
                    help="treat every warning as a failure, including unused signals")
    sp.set_defaults(func=cmd_lint)

    # list / info
    sp = sub.add_parser("list", help="show the effects and chains in this repo")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("info", help="describe one effect and its knobs")
    sp.add_argument("effect")
    sp.set_defaults(func=cmd_info)

    # new-effect
    sp = sub.add_parser("new-effect", help="scaffold a new effect that runs immediately")
    sp.add_argument("name")
    sp.add_argument("--param", "-p", action="append", metavar="NAME[:SCALE]",
                    help="parameter slot, in order; SCALE is raw or q16")
    sp.add_argument("--owner")
    sp.add_argument("--description")
    sp.add_argument("--force", action="store_true", help="overwrite existing files")
    sp.set_defaults(func=cmd_new_effect)

    # gen-audio
    sp = sub.add_parser("gen-audio", help="write the synthetic test wavs to audio/input")
    sp.add_argument("signal", nargs="*",
                    help=f"which to generate: {', '.join(sorted(signals.CATALOG))}")
    sp.set_defaults(func=cmd_gen_audio)

    # doctor
    sp = sub.add_parser("doctor", help="check the toolchain and say what is missing")
    sp.set_defaults(func=cmd_doctor)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ManifestError, PipelineError, BackendError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
