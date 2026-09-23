"""Reference model: delay line with feedback and a dry/wet mix.

Per sample, with a circular buffer of ``delay_samples`` entries::

    old      = buf[addr]
    out      = x*(1 - mix) + old*mix
    buf[addr] = x*(1 - feedback) + old*feedback
    addr     = (addr + 1) % delay_samples

feedback = 0 gives a single repeat; higher values give a decaying train.
mix = 0 is dry only, mix = 1 is the delayed signal only.

Note for whoever owns delay.sv: the RTL registers the buffer read into
``old_sample`` and then uses *that registered value* on the next valid sample
when computing what to store, so its write path sees the previous sample's read
rather than the current one. This model uses the current one, which is the
usual reading of the intent. With feedback = 0 the two agree exactly; the
difference only shows once feedback is turned up. See `wavsim compare`.
"""

from __future__ import annotations

import numpy as np

from . import get


def process(x: np.ndarray, params: dict, fs: int = 48000) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    delay_samples = int(get(params, "delay_samples", 0))
    feedback = float(get(params, "feedback", 0.0))
    mix = float(get(params, "mix", 0.5))

    if delay_samples <= 0:
        # No delay line: the wet path is the input itself.
        return x.copy()

    buf = np.zeros(delay_samples, dtype=np.float64)
    out = np.empty_like(x)
    addr = 0
    for n in range(x.size):
        old = buf[addr]
        out[n] = x[n] * (1.0 - mix) + old * mix
        buf[addr] = x[n] * (1.0 - feedback) + old * feedback
        addr += 1
        if addr == delay_samples:
            addr = 0
    return out
