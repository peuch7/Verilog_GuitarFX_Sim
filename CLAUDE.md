# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

A simulation harness for a capstone guitar effects pedal built on a Zybo Z7 FPGA
mesh. The team has one board and six effects, so effects are developed and
validated in simulation: a `.wav` becomes a 24-bit / 48 kHz sample stream, runs
through a member's SystemVerilog under Verilator or Icarus, and comes back out
as a `.wav`, with metrics against a float reference model.

This repository is the *test harness*, not the pedal firmware.

## Ground rules

**Do not modify files under `rtl/effects/<name>/<name>.sv` unless asked.** Those
are individual team members' designs. The harness exists to measure them, not to
fix them. If a comparison reveals a bug, report it with the evidence and leave
the RTL alone. `rtl/effects/<name>/<name>_top.sv` wrappers are harness
infrastructure and may be edited.

**Keep the two backends identical.** `sim/verilator/sim_main.cpp` and
`sim/icarus/tb_top.sv` implement the same sequence cycle for cycle. Changing the
timing in one without the other silently breaks `make crosscheck`, which is the
main guard on the whole harness. Verify with:

```bash
make crosscheck effect=delay
```

**`resample.py` must not use scipy.** scipy is a dependency and is used freely
in `refmodels/` and analysis, but the wav → stream front end uses the in-repo
polyphase resampler so gold vectors stay bit-identical across machines and scipy
versions. Do not "simplify" it to `resample_poly`.

**Gold vectors are exact.** `tests/gold/*.pcm24` are committed 24-bit outputs. A
one-LSB drift fails the test on purpose. Only regenerate with
`pytest --update-gold` when a behaviour change is intended, and say so.

## Layout

| Path | What |
|---|---|
| `rtl/common/effect_contract.svh` | The interface every effect implements |
| `rtl/effects/<name>/` | A member's module plus its harness wrapper |
| `sim/verilator/sim_main.cpp` | Generic C++ harness; DUT chosen by `-DDUT_TYPE` macro, no codegen |
| `sim/icarus/tb_top.sv` | Same testbench in SV; DUT chosen by `-DDUT_TOP` |
| `tools/wavsim/` | Python: front end, back end, metrics, reference models, CLI |
| `configs/effects/<name>.json` | Knob names, scales, ranges, defaults |
| `tests/` | pytest, running the real RTL through the real harness |

## Commands

```bash
make doctor                     # what is installed, what is missing
make run effect=delay           # wav -> effect -> wav
make compare effect=delay       # RTL vs float reference model
make crosscheck effect=delay    # both simulators must agree byte for byte
make lint                       # verilator --lint-only (warnings shown, errors fail)
make test                       # pytest; --backend icarus to swap simulator
make new-effect name=tremolo    # scaffold an effect that runs immediately
```

The venv is used automatically by every target; there is nothing to activate.
Inside the container, `PYTHONPATH=/work/tools` does the same job.

## Conventions

- Parameter values: **a decimal is natural units, an integer is raw bits.**
  `mix=0.5` == `mix=32767`. This rule is load-bearing in `manifest.py`; do not
  add heuristics on top of it.
- `Manifest.natural()` and `Param._scaled()` are exact inverses. Changing one
  requires changing the other.
- Fixed point: samples Q0.23 signed, knobs Q0.16 unsigned, products 40 bits.
  See `docs/fixed_point.md`.
- Sample streams are little-endian int32 holding 24-bit values. See
  `sim/STREAM_FORMAT.md`. The Icarus text form is an internal detail of
  `backends.py`.

## Known state

`delay` is implemented; the other five effects are passthrough stubs with
complete float reference models that specify what they should do.

`delay.sv` feeds back the buffer read registered from the *previous* valid
sample rather than the current one, so with feedback engaged it diverges from
the reference model (~17 dB SNR instead of ~90 dB).
`tests/test_delay.py::test_feedback_path_known_gap` pins this deliberately and
explains what to do when it is fixed. Do not "fix" it by loosening the test or
by editing the reference model to match.
