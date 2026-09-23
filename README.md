# VerilogFXSim

Test the guitar pedal's effects on real audio without the board.

Feed a `.wav` in, and it is converted to the 24-bit / 48 kHz sample stream the
Zybo Z7's codec path delivers, pushed through your SystemVerilog under
simulation, and written back out as a `.wav` you can listen to. The same run
reports how far the RTL drifted from a floating-point reference model, so
"it sounds about right" becomes a number.

There is one board and six effects. This is how five of us work at once.

```bash
make setup                                  # once
make run effect=delay params="delay_samples=14400,mix=0.5"
# -> audio/output/guitar_delay.wav
```

On Windows, see [docs/getting_started.md](docs/getting_started.md) — the
toolchain runs in a container, and VS Code's "Reopen in Container" is one click.

## What it does

```
 .wav ──► mono, 48 kHz ──► int24 stream ──► YOUR MODULE ──► int24 stream ──► .wav
          (front end)                       (verilator                       (back end)
                                             or icarus)
                                                  │
                                                  └──► compared against a float
                                                       reference model: SNR,
                                                       peak error, latency
```

## The commands

| Command | What it is for |
|---|---|
| `make run effect=delay` | The headline path: wav in, wav out, listen to it. |
| `make compare effect=delay` | RTL vs the float reference model — SNR, worst-case error, latency. |
| `make crosscheck effect=delay` | Proves Verilator and Icarus produce byte-identical output. |
| `make chain config=example_mesh` | Several effects in series, one per board in the mesh. |
| `make trace effect=delay` | A VCD for gtkwave, capped so it stays openable. |
| `make lint` | `verilator --lint-only` over every effect. |
| `make test` | The pytest suite, running the real RTL. |
| `make new-effect name=tremolo` | Scaffolds an effect that already runs end to end. |
| `make doctor` | Says exactly what is missing and how to install it. |

`make help` lists them all. Every target takes `effect=`, `wav=`, `out=`,
`params="mix=0.5,feedback=0.4"`.

Parameter values follow one rule: **a decimal is in natural units, an integer is
raw bits.** `mix=0.5` and `mix=32767` mean the same thing, and neither is a
guess.

## Adding your effect

```bash
make new-effect name=tremolo
make run effect=tremolo          # already works — it is a passthrough
```

That writes the module, its harness wrapper, a manifest, a reference model stub
and a test stub. Then edit `rtl/effects/tremolo/tremolo.sv`. You never touch the
harness, the C++ or the Python.

Read [docs/module_contract.md](docs/module_contract.md) first — it is short, and
it is the only thing your module has to obey.

## Layout

```
rtl/effects/<name>/     your module, plus a thin wrapper onto the standard interface
rtl/common/             the interface contract every effect implements
sim/verilator/          the C++ harness (one file, shared by every effect)
sim/icarus/             the same testbench in SystemVerilog, as a fallback
tools/wavsim/           the Python front end, back end, metrics and reference models
configs/effects/        one manifest per effect: knob names, ranges, defaults
configs/chains/         multi-effect chains
tests/                  pytest suite and committed gold vectors
docs/                   the contract, setup, and fixed-point notes
```

## Documentation

| Document | For |
|---|---|
| [docs/getting_started.md](docs/getting_started.md) | Setting up on Windows, macOS or Linux |
| [docs/module_contract.md](docs/module_contract.md) | Writing an effect — the only rules your module must follow |
| [docs/fixed_point.md](docs/fixed_point.md) | Q formats, overflow, rounding, BRAM budget |
| [docs/architecture.md](docs/architecture.md) | How the harness itself works, for changing it |
| [sim/STREAM_FORMAT.md](sim/STREAM_FORMAT.md) | The sample stream and automation file formats |

## Current state

`delay` and `chorus` are implemented and pass. The other four — `distortion`,
`overdrive`, `reverb`, `echo` — are scaffolded: each has a working passthrough
module, a manifest with real knob definitions, and **a complete float reference
model that specifies what it should do**. Start by reading your effect's
reference model in `tools/wavsim/refmodels/`; that is the target.

`chorus` is worth reading as a worked example before starting your own. It shows
the sequencer pattern that spreads work across the ~32 clocks between samples so
a memory only needs one read port, fixed-point interpolation, and a ROM built
the one way Vivado, Verilator and Icarus all accept.

One known finding, left for the owner to decide on rather than quietly patched:
`delay.sv` feeds back the buffer read from the *previous* sample rather than the
current one, so with feedback engaged it diverges from the reference model.
`tests/test_delay.py::test_feedback_path_known_gap` pins the current behaviour
and explains it.
