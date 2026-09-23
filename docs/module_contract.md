# The module contract

Everything the harness needs from your effect. It is short on purpose: obey this
and `make run effect=<yours>` works, with no changes anywhere else.

## The interface

Your effect keeps whatever ports you like. A thin wrapper, `<name>_top.sv`,
presents the standard interface and maps the parameter bus onto your port names.
`make new-effect` writes both files for you.

```systemverilog
module <name>_top (
    input  logic                            clk,
    input  logic                            rst_n,            // active low
    input  logic signed [`SAMPLE_WIDTH-1:0] sample_in,        // 24-bit signed
    input  logic                            sample_in_valid,
    input  logic [`PARAM_BUS_WIDTH-1:0]     params,           // 8 x 16 bits

    output logic signed [`SAMPLE_WIDTH-1:0] sample_out,
    output logic                            sample_out_valid
);
```

Constants come from [`rtl/common/effect_contract.svh`](../rtl/common/effect_contract.svh).

## The rules

**One valid pulse per sample.** `sample_in_valid` is high for exactly one clock
per input sample. Raise `sample_out_valid` for exactly one clock per output
sample you produce. The harness counts both and tells you if they disagree.

**Only the strobe matters.** `sample_out` is read *only* on cycles where
`sample_out_valid` is high. You may drive it combinationally, or every cycle, or
leave stale data between samples — nobody looks. (`delay.sv` drives it every
clock, which is fine.)

**Latency is yours.** Take as many cycles as you need. The harness measures the
latency, reports it, flushes your pipeline at the end, and compensates for it
before comparing against the reference model.

**Cycles between samples.** By default `sample_in_valid` pulses every 32 clocks.
Real hardware gives you ~2083 at 100 MHz / 48 kHz, but simulating that would be
almost entirely idle cycles. If your design needs more than 32, raise
`cycles_per_sample` in `configs/effects/<name>.json` — that is what it is for.

**Reset.** `rst_n` is active low and held low for 16 cycles before the first
sample, then released one full cycle before the first valid pulse. Honour it if
you have state worth clearing. A module without a reset still runs (`delay.sv`
has none), but then the first run and a rerun are not guaranteed to match.

## Parameters

Eight 16-bit slots on one flat bus. Slot `i` is `params[16*i +: 16]`, or
`` `PARAM(i) `` using the macro. Your wrapper does the slicing:

```systemverilog
delay u_delay (
    .clk, .sample_in, .sample_in_valid,
    .delay_samples (`PARAM(0)),
    .feedback      (`PARAM(1)),
    .mix           (`PARAM(2)),
    .sample_out, .sample_out_valid
);
```

Name the slots in `configs/effects/<name>.json` so the CLI takes
`--param mix=0.5` instead of a magic number:

```json
{ "name": "feedback", "index": 1, "default": 0.4, "scale": "q16",
  "doc": "How much of the delayed signal is fed back." }
```

- `"scale": "raw"` — the integer goes to the bus unchanged. Counts, indices, tap
  numbers.
- `"scale": "q16"` — a 0..1 knob stored as 0..65535. `mix=0.5` becomes 32768.
- `"factor"` / `"offset"` — natural units per bit, when the slot holds a real
  quantity. Chorus stores its LFO rate in centi-hertz with `"factor": 0.01`, so
  the RTL sees `100` and the reference model sees `1.0 Hz`.

Parameters can also change mid-clip; see *Parameter automation files* in
[`sim/STREAM_FORMAT.md`](../sim/STREAM_FORMAT.md).

## Your reference model

The float model in `tools/wavsim/refmodels/<name>.py` is the specification your
RTL is measured against. **Write it before the RTL**, or at least read it first:

```bash
make compare effect=<name>
```

reports SNR, worst-case error in LSBs, and latency. Roughly what to expect:

| SNR | Reading |
|---|---|
| 85 dB and up | Fixed-point rounding only. This is a match. |
| 40–85 dB | Something real differs: rounding strategy, a saturation, an off-by-one. |
| under 40 dB | A design bug. Compare the impulse responses first. |

For reference, `delay` with feedback off scores ~90 dB. With feedback on it
scores ~17 dB, because its feedback path is genuinely one sample late.

## What to check before you say it works

```bash
make lint effect=<name>        # width truncation warnings are the ones that bite
make compare effect=<name>     # against your reference model
make crosscheck effect=<name>  # Verilator and Icarus must agree exactly
make test                      # the pytest suite
make run effect=<name>         # then actually listen to the wav
```

`crosscheck` is worth running even when everything looks fine. If the two
simulators disagree, the usual cause is code that depends on an uninitialised
value, which will also behave differently on real hardware.

## Fixed point

Read [fixed_point.md](fixed_point.md) before choosing your widths. The short
version: samples are Q0.23, knobs are Q0.16 unsigned, and a 24×16 product needs
40 bits before you shift it back down.
