# The sample stream format

Everything between the Python front end, the simulators, and the Python back end
is one file format. A chain stage, a crosscheck, a gold vector and a plot all
read the same bytes.

## Canonical form: `.pcm24`

Raw **little-endian `int32`**, one per sample, no header. Each value is a signed
24-bit sample sign-extended into 32 bits, so the range is
`-8388608 .. 8388607` (`-2^23 .. 2^23-1`).

Mono, at **48 kHz**, matching the SSM2603 codec path on the Zybo Z7.

32 bits per sample rather than packed 3-byte frames, at the cost of 25% more
disk, because it reads in one line everywhere:

| Where | How |
|---|---|
| Python | `np.fromfile(path, dtype="<i4")` |
| C++ | `fread(buf, 4, n, f)` |
| SystemVerilog | `$fread` on a 32-bit word |

Packed 24-bit would need bit-shuffling in three languages and would be the first
thing to get wrong.

## Sidecar: `.pcm24.meta.json`

Written next to each stream so the back end can rebuild a wav without being told
anything about it:

```json
{
  "sample_rate": 48000,
  "n_samples": 196800,
  "width": 24,
  "source": "delay input",
  "notes": {}
}
```

The sidecar is informational. A stream is still readable without one; only the
sample count and rate are lost, and the count is implied by the file size.

## Text form: `.pcm24.txt`

The same values in decimal, one per line. Used **only** by the Icarus backend.

`$fread` fills a vector in big-endian order, and byte-swapping inside
SystemVerilog is not worth the risk for a fallback path, so
`wavsim/backends.py` converts to text on the way in and back on the way out.
The canonical on-disk format is unchanged, and `wavsim crosscheck` confirms both
backends still produce identical `.pcm24` output.

## Parameter automation files

Optional, plain text, passed with `--automation`:

```
# sample_index  param_index  value
0      2  32768     # mix starts at half
48000  2  65535     # fully wet one second in
96000  0  24000     # and a longer delay at two seconds
```

`#` starts a comment. Events apply just before the named input sample is fed in,
and both backends read the same file. This is how a knob sweep gets tested
rather than just a set of static settings.

## Converting by hand

```python
from wavsim import stream, wavio

samples = stream.read("build/verilator/delay/work/out.pcm24")   # int32
wavio.write_wav("out.wav", stream.samples_to_float(samples), 48000)
```

`stream.float_to_samples` and `stream.samples_to_float` are exact inverses:
float64 has enough mantissa to hold a 24-bit integer scaled by `2^-23` without
loss, so a round trip never drifts.
