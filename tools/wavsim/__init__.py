"""wavsim: .wav -> SystemVerilog effect -> .wav simulation harness.

The pipeline is always the same four steps:

    wav file  --wavio-->  mono float  --stream-->  24-bit sample stream
              --backend (verilator | icarus)-->  output sample stream
              --stream/wavio-->  wav file

Everything else (metrics, plots, chains, scaffolding) is built on top of those.
"""

__version__ = "0.1.0"

SAMPLE_RATE = 48000
"""Rate the Zybo's SSM2603 codec path runs at. All streams are at this rate."""

SAMPLE_WIDTH = 24
"""Width of one audio sample in the RTL, in bits."""

SAMPLE_MAX = (1 << (SAMPLE_WIDTH - 1)) - 1   # 8388607
SAMPLE_MIN = -(1 << (SAMPLE_WIDTH - 1))      # -8388608
SAMPLE_SCALE = float(1 << (SAMPLE_WIDTH - 1))  # 8388608.0

N_PARAMS = 8
"""Number of 16-bit knob slots on the standard effect interface."""

PARAM_WIDTH = 16
PARAM_MAX = (1 << PARAM_WIDTH) - 1  # 65535
