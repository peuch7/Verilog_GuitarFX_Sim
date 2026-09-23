# Fixed point in this project

Audio DSP in RTL is mostly bookkeeping about where the binary point is. This is
the convention everything here uses, so the six effects stay compatible when
they are chained.

## Formats

**Samples — Q0.23, signed, 24 bits.** One sign bit and 23 fractional bits, so
the range is `-1.0 .. +1.0 - 2^-23`, stored as `-8388608 .. 8388607`. This
matches the SSM2603 codec, and it is what `sample_in` and `sample_out` carry.

**Knobs — Q0.16, unsigned, 16 bits.** `0 .. 65535` representing `0.0 .. 1.0`.
Note the ceiling: full scale is **65535, not 65536**, so a "fully wet" knob is
`65535/65536 = 0.99998` of the signal. That is about -0.0001 dB and inaudible,
but it means a mix never reaches mathematically exact unity. `delay.sv`
documents this deliberately.

Slots holding counts (delay lengths, tap numbers) are plain unsigned integers
instead; the manifest says which is which.

## Multiplying

A 24-bit sample times a 16-bit knob needs **40 bits**, not 41:

```systemverilog
logic signed [39:0] product;
assign product = sample * $signed({1'b0, knob});   // zero-extend the unsigned knob
assign result  = product >>> 16;                   // back to Q0.23
```

Two things go wrong here regularly:

1. **Forgetting to zero-extend the knob.** `{1'b0, knob}` makes it explicitly
   positive before `$signed`. Without it, a knob above 32767 is read as
   negative and the effect inverts.
2. **Using `>>` instead of `>>>`.** A logical shift on a negative product
   corrupts the sign. Always `>>>` on signed values.

Summing two of these products still fits in 40 bits when the coefficients sum to
at most 1.0 — which is why `delay.sv` can write
`cur*(65535-mix) + old*mix` into a 40-bit signal safely.

## Overflow

A convex combination (`a*x + (1-a)*y` with `0 <= a <= 1`) cannot exceed full
scale, so dry/wet mixes and feedback blends are safe by construction. Anything
else — a gain stage, a sum of several taps, a comb filter's feedback — can
exceed it and must **saturate, not wrap**. Wrapping turns a loud note into a
full-scale sign flip, which is an audible click:

```systemverilog
// saturate to Q0.23
always_comb begin
    if      (wide >  40'sd8388607)  clamped =  24'sd8388607;
    else if (wide < -40'sd8388608)  clamped = -24'sd8388608;
    else                            clamped =  wide[23:0];
end
```

The harness helps you find this: `wavsim run` reports how many output samples
landed exactly on a rail, and `tests/test_delay.py::test_full_scale_input_does_not_wrap`
checks it by linearity — halving the input must halve the output, which a wrap
breaks badly and a saturation breaks only mildly.

## Rounding

Truncating (`>>> 16`) biases every sample slightly negative, which across a
feedback loop accumulates into DC offset. Rounding costs one adder:

```systemverilog
assign result = (product + 40'sd32768) >>> 16;   // round half up
```

`delay.sv` truncates. At 90 dB SNR against the reference it does not matter
there, but inside a reverb's recirculating combs it would.

## Budgeting BRAM

A Zybo Z7-10 has 60 BRAM blocks of 36 Kb, about 270 kB total, and the rest of
the design needs some.

| At 48 kHz | Samples | At 24 bits |
|---|---|---|
| 1 ms | 48 | 144 B |
| 20 ms (chorus) | 960 | 2.9 kB |
| 100 ms | 4800 | 14 kB |
| 1 s (delay max) | 48000 | 144 kB |

`delay.sv` reserves the full second, which is ~144 kB on its own — over half the
device. The Schroeder reverb's six delay lines come to about 27 kB. If the mesh
puts several effects on one board, this is the budget to check first, before
anyone writes the RTL.

Declaring the buffer with `(* ram_style = "block" *)` (as `delay.sv` does) keeps
Vivado from inferring distributed LUT RAM and consuming the fabric instead.
