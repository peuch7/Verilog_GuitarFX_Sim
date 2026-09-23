# How wavsim works

For anyone changing the harness itself. If you only want to write an effect,
[module_contract.md](module_contract.md) is the shorter document you want.

The job is narrow: get audio into a simulator, get it back out, and say how far
the result is from what it should be. Almost every design choice below follows
from wanting that to work identically on two simulators, three operating systems
and inside a container.

---

## The path

```
  .wav ─► load_input ─► float64 mono @48k ─► float_to_samples ─► int32 stream (.pcm24)
                                                                       │
                                            ┌──────────────────────────┘
                                            ▼
                                    Backend.run()
                          verilator: sim_<effect> binary
                          icarus:    vvp sim.vvp   (via decimal text)
                                            │
                                            ▼
                             int32 stream ─► samples_to_float ─► write_wav ─► .wav
                                            │
                                            └─► metrics.compare() against refmodels
```

Concretely, `wavsim run --effect delay` is:

| Step | Where |
|---|---|
| parse args, load the manifest | `cli.cmd_run` → `manifest.Manifest.load` |
| resolve knobs to 8 bus words | `manifest.Manifest.resolve` |
| wav → mono float64 @ 48 kHz | `pipeline.load_input` → `wavio.read_wav`, `resample.resample` |
| float → int24, write stream | `stream.float_to_samples`, `stream.write` |
| build if stale, run the sim | `backends.VerilatorBackend.build` / `.run` |
| read stream, int24 → float | `stream.read`, `stream.samples_to_float` |
| float → wav | `wavio.write_wav` |

`pipeline.process_array` is the single chokepoint: `run`, `chain`, `compare` and
every test go through it. If you are adding a feature that touches how audio
reaches the simulator, it belongs there and nowhere else.

---

## The modules

| Module | Responsibility |
|---|---|
| `paths.py` | Every filesystem location. Nothing else hardcodes a path. |
| `wavio.py` | RIFF parsing and PCM writing. No dependencies beyond numpy. |
| `resample.py` | Polyphase windowed-sinc rate conversion. **Deliberately scipy-free.** |
| `stream.py` | The int32 sample stream, its sidecar, and the float conversions. |
| `manifest.py` | Effect metadata; the bits ↔ natural-units mapping. |
| `backends.py` | Building and invoking the two simulators behind one interface. |
| `pipeline.py` | Orchestration: wav in, RTL in the middle, wav out. Chains. |
| `refmodels/` | Float reference models — the specification each effect targets. |
| `metrics.py` | Alignment, SNR, error, THD. Turning output into a verdict. |
| `signals.py` | Synthetic stimulus, so no audio has to be committed. |
| `scaffold.py` | `new-effect` templates. |
| `plots.py` | Optional matplotlib output. Never imported at startup. |
| `cli.py` | Argument parsing and presentation. No logic lives here. |

### Why `wavio` hand-parses RIFF

The stdlib `wave` module rejects `WAVE_FORMAT_EXTENSIBLE` (0xFFFE) and float
files, which is a large fraction of real DAW exports. `_parse_fmt` walks the
chunks itself and, for extensible files, reads the real format tag out of the
first two bytes of the SubFormat GUID. Writing still goes through `wave`,
because plain 24-bit PCM out is all anyone needs.

### Why `resample` does not use scipy

scipy is a dependency and is used freely in `refmodels/` and analysis. The wav →
stream front end is the exception, and it is deliberate: it sits upstream of
every run on real audio, so if it produced subtly different output across scipy
versions, the container and the host would disagree and any gold vector sourced
from a non-48 kHz wav would stop being portable. Pinning it to in-repo code
removes the question entirely.

(The gold vector committed today uses a synthetic 48 kHz signal and so never
calls the resampler — but the first vector recorded from a 44.1 kHz wav would,
and by then the dependency would be hard to unpick.)

`tests/test_harness.py::test_resampler_does_not_use_scipy` enforces this, so it
cannot be undone by accident.

The implementation is a standard polyphase decomposition. For 44100 → 48000 the
ratio reduces to L=160, M=147, and each output sample reads one phase of the
prototype filter:

```
y[n] = Σ_k h[p + k·L] · x[base − k],   p = m mod L,  base = ⌊m/L⌋,  m = n·M + c
```

`c` is the prototype's centre tap, which cancels the filter's group delay so the
output stays time-aligned with the input. Gathers are chunked at 65536 output
samples to bound peak memory at `taps × chunk` floats. Measured on a 1 kHz sine
at 44.1 → 48 kHz: worst spurious component −101.8 dB.

---

## Selecting the DUT without codegen

There is one C++ harness, `sim/verilator/sim_main.cpp`, shared by every effect.
Verilator names its generated class after the top module, so the harness takes
both the header and the type as macros:

```cpp
#include DUT_HEADER
using Dut = DUT_TYPE;
```

and `backends.py` passes:

```
-CFLAGS '-DDUT_HEADER=\"Vdelay_top.h\" -DDUT_TYPE=Vdelay_top'
```

Icarus does the same thing through the preprocessor — `tb_top.sv` instantiates
`` `DUT_TOP ``, supplied as `iverilog -DDUT_TOP=delay_top`.

This is why the parameter bus is a flat packed `[127:0]` rather than an unpacked
array: it makes the port list identical for every effect, so no generated glue
is needed on either side. Verilator emits it as a 4-word array, which you can
confirm in any build:

```
$ grep params build/verilator/delay/obj_dir/Vdelay_top.h
VL_INW(&params,127,0,4);
```

`write_param()` in the harness therefore packs slot `i` into word `i/2`, half
`i%2`.

### Sample width

`VL_IN(&sample_in,23,0)` — Verilator hands you 24 valid bits inside a 32-bit
word, zero-extended. Reading `sample_out` without sign-extending is the single
easiest way to break this harness, so both directions go through helpers in
`stream_io.h`:

```cpp
sign_extend24(v)   // reading a port:  0xFFFFFF → signed
to_field24(v)      // writing a port:  signed → 24-bit field
```

---

## The timing model

Both backends implement the same sequence. Getting this wrong in one of them is
the failure mode the whole design guards against, so the rules are explicit:

1. Drive `rst_n` low for **16 cycles**.
2. Release it, then clock **one idle cycle**.
3. Pulse `sample_in_valid` for one cycle every `cycles_per_sample` clocks
   (default 32).
4. Capture `sample_out` on **every cycle where `sample_out_valid` is high** —
   never unconditionally. `delay.sv` drives `sample_out` on every clock and only
   the strobe marks the real samples.
5. After the last input, clock `flush_samples × cycles_per_sample` more cycles
   to drain the pipeline.

Step 2 exists only so the two backends can be made identical; without it
Verilator raised reset and the first valid strobe in the same cycle, which
Icarus could not reproduce cleanly.

### cycles_per_sample

Real hardware gives a module ~2083 clocks per sample at 100 MHz / 48 kHz.
Simulating that ratio would spend 98% of its time on idle cycles, so the gap is
shrunk to just above the DUT's pipeline latency. It is per-effect in the
manifest because that is a property of the design, not of the harness.

### The capture-edge subtlety

This is the one piece of the two backends that is *not* written the same way,
and it has to be that way.

Verilator's `eval()` at the rising edge applies non-blocking updates
immediately, so reading a port after `eval()` returns the **post-edge** value.
In SystemVerilog, an `always @(posedge clk)` block reads the **pre-edge** value,
because NBA updates land later in the timestep. Writing the obvious thing in
both would shift the Icarus output by exactly one sample.

So `tb_top.sv` captures on the **falling** edge, where the values assigned at
the preceding rising edge have settled:

```systemverilog
always @(negedge clk) begin
    if (capture_enable && sample_out_valid) begin
        if (first_out_cycle < 0) first_out_cycle = cycle - 1;
        ...
```

The `cycle - 1` is the same issue in the latency counter: at that falling edge
the counter has already counted the edge that produced the sample, while
`first_in_cycle` is recorded before its edge.

**If you change the timing in either backend, change both, then run
`make crosscheck`.** That command exists specifically to catch this.

---

## Parameters: bits and natural units

One rule, applied everywhere:

> A decimal value is in **natural units**. An integer is **raw bus bits**.

`mix=0.5` and `mix=32767` are the same setting. `Param._scaled()` and
`Manifest.natural()` are exact inverses of each other:

```
bits    = round( (natural − offset) / factor × (65535 if q16 else 1) )
natural = (bits / 65535 if q16 else bits) × factor + offset
```

`factor`/`offset` are how a 16-bit slot carries a real quantity. Chorus stores
its LFO rate in centi-hertz with `"factor": 0.01`, so the RTL sees `100` and the
reference model sees `1.0` Hz. `min`/`max` in the manifest are checked against
the **bits**, after conversion.

Do not add heuristics on top of this rule. The temptation is to guess that
`mix=1` means "fully wet" rather than "one bit"; resist it, because then no
value is unambiguous.

---

## Backends

`Backend` has three methods that matter: `available()`, `build()`, `run()`.
`get_backend("auto", manifest)` returns Verilator if it is installed, else
Icarus, else raises with the install hint.

### Build staleness

Rebuilds are timestamp-driven: sources plus the harness files versus the output
binary. Verilator additionally records its build flags in `build_flags.json`, so
turning tracing on or off forces a rebuild — otherwise you would get a binary
that rejects `--trace` while claiming to be current.

### Build layout

```
build/<backend>/<effect>/
    obj_dir/sim_<effect>      verilator binary
    sim.vvp                   icarus binary
    build_flags.json          verilator only
    stats.json                last run's summary
    work/                     in.pcm24, out.pcm24 for the last run
    crosscheck/               kept separate so it cannot clobber work/
```

`build/` is a named Docker volume, not part of the bind mount, so container and
host builds cannot collide — and on Windows, object files stay out of the slow
cross-filesystem mount.

### Why Icarus uses text

`$fread` fills a vector in big-endian order, and byte-swapping inside
SystemVerilog is not worth the risk on a fallback path. `IcarusBackend.run()`
converts `.pcm24` → decimal text on the way in and back on the way out. The
canonical on-disk format never changes, and `crosscheck` compares `.pcm24`, so
the conversion is covered.

### Adding a third backend

Subclass `Backend`, implement the three methods, register it in `BACKENDS`. The
contract is: given an input `.pcm24` and 8 parameter words, produce an output
`.pcm24` and a `stats.json`. Nothing above `backends.py` needs to know.

---

## Comparison

`metrics.compare()` aligns before measuring. A design that is correct but
delayed by one sample would otherwise look catastrophically wrong, so
`find_lag()` cross-correlates via FFT over a leading window (≤65536 samples) and
the lag is reported separately from the error.

Read the numbers together:

| Field | Meaning |
|---|---|
| `lag` | Constant offset. Usually pipeline latency, not a bug. |
| `snr_db` | Error energy vs reference energy. The headline number. |
| `max_abs_error_lsb` | Worst single sample, in LSBs of the 24-bit word. |
| `clipped` | Samples on a rail. A stage is probably overflowing. |

Rough bands: 85 dB+ is rounding only; 40–85 dB means something real differs;
below 40 dB is a design bug.

`refmodels` are loaded by the `"module:function"` string in the manifest, via
`importlib`. They receive **natural** units, never bits.

---

## Tests

`tests/conftest.py` provides two fixtures:

- `backend` — session-scoped, from `--backend`, skipping if unavailable.
- `assert_gold` — compares against `tests/gold/<name>.pcm24`, exactly.

Gold vectors store 24-bit integers, so a one-LSB drift fails on purpose. When
the file is missing, the fixture writes it and then **skips** rather than
passing, so a broken run cannot silently bless itself. Regenerate only with
`pytest --update-gold`, and say why in the commit.

Tests run the real RTL through the real harness. That is slower than mocking but
it is the point: a failure means either a design bug or a harness regression,
and those are the two things worth catching.

---

## Invariants

Things that will break quietly if you change one side only:

1. **`sim_main.cpp` and `tb_top.sv` implement the same sequence.** Verify with
   `make crosscheck`.
2. **`Param._scaled()` and `Manifest.natural()` are inverses.** Changing one
   requires changing the other.
3. **`resample.py` stays scipy-free.** Gold vectors depend on it being identical
   everywhere.
4. **Gold vectors are exact.** Never loosen a comparison to make one pass.
5. **`stream.float_to_samples` / `samples_to_float` round-trip exactly.** float64
   has 53 mantissa bits, so a 24-bit integer scaled by 2⁻²³ is lossless. Do not
   introduce float32 anywhere in that path.
6. **`plots.py` is never imported at startup.** matplotlib is a dev extra.

---

## Things that already caught real bugs

Worth knowing, because they will catch the next one too.

- **`make crosscheck`** found that Icarus 11 (which Debian, and therefore the
  container, ships) rejects `void'(...)` casts that Icarus 12 accepts.
- **Running `make` inside the container** found that the Makefile preferred the
  bind-mounted macOS `.venv`, whose interpreter cannot execute under Linux. The
  Makefile now probes the interpreter rather than testing for the directory.
- **`compare` on `delay`** found that `delay.sv` feeds back the buffer read
  registered from the *previous* valid sample, giving ~17 dB SNR with feedback
  engaged against ~90 dB with it off. Pinned by
  `test_delay.py::test_feedback_path_known_gap`.
