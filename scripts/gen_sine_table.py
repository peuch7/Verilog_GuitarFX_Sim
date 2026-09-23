#!/usr/bin/env python3
"""Generate the chorus LFO sine ROM and its fixed-point constants.

Run from the repository root:

    python3 scripts/gen_sine_table.py

The table is generated rather than computed in RTL because Vivado does not
reliably support real-valued system functions ($sin, $rtoi) in synthesisable
code, even though both simulators evaluate them happily. Explicit per-entry
assignments inside an initial block are the one ROM-initialisation form that
Vivado, Verilator and Icarus all accept:

  * Vivado infers a ROM and honours the initial values.
  * Icarus rejects `localparam` unpacked arrays, so that form is unusable.
  * $readmemh would work in all three, but adds a runtime file dependency whose
    path has to be right in simulation and in the Vivado project.

Standard library only, so it runs without the venv.
"""

from __future__ import annotations

import math
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "rtl" / "effects" / "chorus" / "chorus_sine_table.svh"

ENTRIES = 1024   # points per full cycle; the LFO interpolates between them
WIDTH = 24       # Q23 signed, so the amplitude step does not dominate the delay
PEAK = (1 << (WIDTH - 1)) - 1

SAMPLE_RATE = 48000
PHASE_W = 32          # nominal phase width; the accumulator carries more
PHASE_INC_FRAC = 16   # extra fractional bits kept in the accumulator
DELAY_Q = 20          # fractional bits on the delay, in samples

# These are derived rather than typed in. Writing them by hand is how this file
# first shipped a phase constant that was 60 ppm off, which showed up as the LFO
# drifting away from the reference model over a few seconds - a slow, unobvious
# failure that looked like a design limit rather than a typo.
PHASE_INC_PER_CENTIHZ = round(
    (1 << (PHASE_W + PHASE_INC_FRAC)) / (100 * SAMPLE_RATE)
)
DELAY_PER_TENTH_MS = round(SAMPLE_RATE / 1000.0 * 0.1 * (1 << DELAY_Q))


def main() -> int:
    values = [
        int(round(math.sin(2.0 * math.pi * i / ENTRIES) * PEAK))
        for i in range(ENTRIES)
    ]
    # Rounding can never push a sine past the peak, but assert it rather than
    # trust it: an out-of-range literal would silently truncate in the RTL.
    assert all(-PEAK - 1 <= v <= PEAK for v in values)

    lines = [
        "// chorus_sine_table.svh - GENERATED, do not edit.",
        "//",
        f"// One full sine cycle, {ENTRIES} points, Q{WIDTH - 1} signed.",
        "// Regenerate with: python3 scripts/gen_sine_table.py",
        "//",
        "// Explicit assignments rather than a localparam array: Icarus does not",
        "// accept localparam unpacked arrays, and Vivado does not accept $sin in",
        "// synthesisable code. This form works in all three tools.",
        "",
        "`ifndef CHORUS_SINE_TABLE_SVH",
        "`define CHORUS_SINE_TABLE_SVH",
        "",
        f"`define CHORUS_SINE_ENTRIES {ENTRIES}",
        f"`define CHORUS_SINE_WIDTH   {WIDTH}",
        "",
        f"// 2^{PHASE_W + PHASE_INC_FRAC} / (100 * {SAMPLE_RATE}) "
        f"= {(1 << (PHASE_W + PHASE_INC_FRAC)) / (100 * SAMPLE_RATE):.4f}",
        f"`define CHORUS_PHASE_W        {PHASE_W}",
        f"`define CHORUS_PHASE_INC_FRAC {PHASE_INC_FRAC}",
        f"`define CHORUS_PHASE_INC_PER_CENTIHZ {PHASE_INC_PER_CENTIHZ}",
        "",
        f"// 0.1 ms * {SAMPLE_RATE / 1000:.0f} samples/ms * 2^{DELAY_Q} "
        f"= {SAMPLE_RATE / 1000.0 * 0.1 * (1 << DELAY_Q):.1f}",
        f"`define CHORUS_DELAY_Q            {DELAY_Q}",
        f"`define CHORUS_DELAY_PER_TENTH_MS {DELAY_PER_TENTH_MS}",
        "",
        "`define CHORUS_SINE_INIT \\",
    ]

    body = [
        f"    sine_tab[{i}] = {WIDTH}'sd{v};" if v >= 0
        else f"    sine_tab[{i}] = -{WIDTH}'sd{-v};"
        for i, v in enumerate(values)
    ]
    # One macro so the RTL stays a single `CHORUS_SINE_INIT line.
    lines += [f"{line} \\" for line in body[:-1]]
    lines.append(body[-1])
    lines += ["", "`endif", ""]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines))
    print(f"wrote {OUT_PATH.relative_to(REPO_ROOT)}  ({ENTRIES} entries, Q{WIDTH - 1})")
    print(f"  phase step per centi-hertz : {PHASE_INC_PER_CENTIHZ}")
    print(f"  delay units per 0.1 ms     : {DELAY_PER_TENTH_MS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
